from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import psycopg
from fastapi import FastAPI, Request
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from image_gen import _SCHEMA_SQL  # canonical schema lives in the root library

from ._base import LifespanDependency
from ._config import logger


def _resolve_pg_host_user(ws, endpoint_name: str) -> tuple[str, str]:
    host = os.environ.get("PGHOST", "")
    user = os.environ.get("PGUSER", "")
    if not host:
        try:
            endpoints = list(ws.postgres.list_endpoints(
                parent=f"projects/{endpoint_name.split('/')[1]}/branches/{endpoint_name.split('/')[3]}"
            ))
            if endpoints:
                host = endpoints[0].status.hosts.host
        except Exception as exc:
            logger.warning("Could not resolve PGHOST from SDK: %s", exc)
    if not user:
        user = (
            os.environ.get("DATABRICKS_CLIENT_ID")
            or ws.config.client_id
            or ws.current_user.me().user_name
            or ""
        )
    return host, user


def _make_pool(ws, endpoint_name: str, database: str) -> ConnectionPool:
    """Create a psycopg ConnectionPool using Lakebase Autoscaling OAuth tokens.

    Each connection mints a fresh OAuth token at connect time and registers the pgvector
    type so VECTOR columns can round-trip as Python lists.
    """

    host, user = _resolve_pg_host_user(ws, endpoint_name)
    port = os.environ.get("PGPORT", "5432")

    class OAuthConnection(psycopg.Connection):
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs):
            cred = ws.postgres.generate_database_credential(endpoint=endpoint_name)
            kwargs["password"] = cred.token
            return super().connect(conninfo, **kwargs)

    def _configure(conn: psycopg.Connection) -> None:
        register_vector(conn)

    conninfo = f"dbname={database} user={user} host={host} port={port} sslmode=require"
    pool = ConnectionPool(
        conninfo=conninfo,
        connection_class=OAuthConnection,
        configure=_configure,
        min_size=2,
        max_size=10,
        max_lifetime=2700,  # 45 min — recycle before 1-hour token expiry
        open=False,
        kwargs={"row_factory": dict_row},
    )
    return pool


def _split_sql_statements(sql: str) -> list[str]:
    """Split a multi-statement SQL script on top-level semicolons, ignoring semicolons and `--`
    line comments inside single-quoted string literals (with '' escapes). _SCHEMA_SQL has no
    dollar-quoted blocks, so this single-pass scanner is sufficient. `--` comments are handled
    inline (only when outside a string) rather than pre-stripped by line, so a literal line that
    begins with `--` inside a string (e.g. free-text seed instructions) is preserved intact."""
    stmts: list[str] = []
    buf: list[str] = []
    in_str = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("''")  # escaped quote inside a string literal
                    i += 2
                    continue
                in_str = False
            buf.append(ch)
        else:
            if ch == "-" and i + 1 < n and sql[i + 1] == "-":
                # line comment (outside a string): skip to end of line, keep the newline
                nl = sql.find("\n", i)
                i = n if nl == -1 else nl
                continue
            if ch == "'":
                in_str = True
                buf.append(ch)
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    stmts.append(stmt)
                buf = []
            else:
                buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def _bootstrap_schema(ws, endpoint_name: str, database: str) -> None:
    """Run CREATE EXTENSION + table DDL on a one-shot autocommit connection *before* opening
    the pool, so per-connection `register_vector` callbacks find the type on every connect.

    Statements are executed INDIVIDUALLY (not as one multi-statement query): a single failing
    statement — e.g. `CREATE EXTENSION` raising "must be owner" for a non-owner service
    principal — must not abort the transaction and skip everything after it (that previously
    left newly-added tables like eval_criteria uncreated on existing databases). Per-statement
    "already exists"/"must be owner" errors are expected and logged at debug; anything else is
    a warning. All DDL is idempotent (IF NOT EXISTS / ON CONFLICT).
    """
    host, user = _resolve_pg_host_user(ws, endpoint_name)
    port = os.environ.get("PGPORT", "5432")
    conninfo = f"dbname={database} user={user} host={host} port={port} sslmode=require"
    cred = ws.postgres.generate_database_credential(endpoint=endpoint_name)
    with psycopg.connect(conninfo, password=cred.token, autocommit=True) as boot:
        for stmt in _split_sql_statements(_SCHEMA_SQL):
            try:
                boot.execute(stmt)
            except Exception as exc:
                msg = str(exc)
                if "must be owner" in msg or "already exists" in msg:
                    logger.debug("Schema stmt skipped (%s): %s", msg.splitlines()[0], stmt[:60])
                else:
                    logger.warning("Schema stmt failed: %s | stmt: %s", msg.splitlines()[0], stmt[:80])


class _DatabasePoolDependency(LifespanDependency):
    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        endpoint_name = os.environ.get("ENDPOINT_NAME", "")
        if not endpoint_name:
            logger.warning("ENDPOINT_NAME not set — Lakebase pool not created")
            app.state.db_pool = None
            yield
            return

        ws = app.state.workspace_client
        database = os.environ.get("PGDATABASE", "postgres")

        try:
            # Per-statement execution (see _bootstrap_schema): individual "already exists"/
            # "must be owner" errors are handled inside; this guard is for a hard connection
            # failure only. Idempotent DDL means it's safe to run on every startup.
            _bootstrap_schema(ws, endpoint_name, database)
            logger.info("Lakebase schema bootstrap complete")
        except Exception as exc:
            logger.warning("Schema bootstrap could not run (continuing): %s", exc)

        pool = _make_pool(ws, endpoint_name, database)
        pool.open(wait=True, timeout=30.0)
        logger.info(f"Lakebase Autoscaling pool created (endpoint={endpoint_name})")

        app.state.db_pool = pool
        yield
        pool.close()
        logger.info("Lakebase pool closed")

    @staticmethod
    def __call__(request: Request) -> ConnectionPool:
        pool = request.app.state.db_pool
        if pool is None:
            raise RuntimeError("Lakebase pool not available — is ENDPOINT_NAME set?")
        return pool
