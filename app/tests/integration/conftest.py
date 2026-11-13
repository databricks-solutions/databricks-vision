"""Postgres + pgvector fixtures for integration tests.

Point TEST_DATABASE_URL at a disposable server you can CREATE DATABASE on, e.g.

    docker run --rm -d --name vision-test-pg -p 127.0.0.1:5433:5432 -e POSTGRES_HOST_AUTH_METHOD=trust pgvector/pgvector:pg17
    export TEST_DATABASE_URL=postgresql://postgres@localhost:5433/postgres

Each session creates its own throwaway database (vision_test_<random>), bootstraps it with the
production `_SCHEMA_SQL` (statement by statement, exactly like `_bootstrap_schema`), and drops it
afterwards — existing databases on the server are never touched.

Without TEST_DATABASE_URL these tests skip. CI sets REQUIRE_DB_TESTS=1, which turns that skip into
a failure so the suite can't go green by silently not running.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from databricks_vision.backend.core._database import _split_sql_statements
from image_gen import _SCHEMA_SQL

SCHEMA_STATEMENTS = _split_sql_statements(_SCHEMA_SQL)
# Re-run after each test so every test starts from the seeded baseline.
_SEED_STATEMENTS = [
    s for s in SCHEMA_STATEMENTS
    if s.startswith("INSERT INTO eval_criteria") or s.startswith("INSERT INTO folders")
]
_RESET_SQL = [
    "TRUNCATE batch_runs, generated_images, image_versions, style_guidelines, recipes RESTART IDENTITY CASCADE",
    "DELETE FROM folders",
    "DELETE FROM eval_criteria",
    *_SEED_STATEMENTS,
]


def apply_schema(conninfo: str) -> None:
    """Apply every schema statement on an autocommit connection. Unlike production (which
    tolerates 'already exists' / 'must be owner'), any error here fails the test run."""
    with psycopg.connect(conninfo, autocommit=True) as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(stmt)


@pytest.fixture(scope="session")
def pg_server_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        msg = "TEST_DATABASE_URL not set — integration tests need Postgres + pgvector"
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            pytest.fail(msg + " (REQUIRE_DB_TESTS=1)")
        pytest.skip(msg)
    host = conninfo_to_dict(url).get("host") or ""
    if "databricks" in host:
        pytest.fail(f"Refusing to run integration tests against a Databricks-hosted database ({host})")
    return url


@pytest.fixture(scope="session")
def test_db_url(pg_server_url) -> Iterator[str]:
    name = f"vision_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(pg_server_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield make_conninfo(pg_server_url, dbname=name)
    finally:
        with psycopg.connect(pg_server_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def bootstrapped_db_url(test_db_url) -> str:
    # Twice: the second pass proves the bootstrap is idempotent, which every app restart relies on.
    apply_schema(test_db_url)
    apply_schema(test_db_url)
    return test_db_url


@pytest.fixture(scope="session")
def pool(bootstrapped_db_url) -> Iterator[ConnectionPool]:
    from pgvector.psycopg import register_vector

    # Same row factory + per-connection vector registration as core/_database._make_pool.
    p = ConnectionPool(
        conninfo=bootstrapped_db_url,
        kwargs={"row_factory": dict_row},
        configure=register_vector,
        min_size=1,
        max_size=4,
        open=False,
    )
    p.open(wait=True, timeout=30)
    try:
        yield p
    finally:
        p.close()


@pytest.fixture
def db(pool) -> Iterator[ConnectionPool]:
    """The shared pool, reset to the seeded baseline after the test."""
    yield pool
    with pool.connection() as conn:
        for stmt in _RESET_SQL:
            conn.execute(stmt)
        conn.commit()


@pytest.fixture
def db_client(app, db):
    """TestClient whose app has a real Lakebase-equivalent pool attached."""
    from fastapi.testclient import TestClient

    app.state.db_pool = db
    return TestClient(app)


def fetch(pool: ConnectionPool, sql: str, params: tuple = ()) -> list[dict]:
    with pool.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        conn.commit()
    return rows


def execute(pool: ConnectionPool, sql: str, params: tuple = ()) -> None:
    with pool.connection() as conn:
        conn.execute(sql, params)
        conn.commit()
