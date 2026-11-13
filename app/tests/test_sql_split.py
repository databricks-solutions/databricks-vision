"""_split_sql_statements runs the schema bootstrap one statement at a time (see _bootstrap_schema).

A wrong split silently drops or corrupts DDL on startup — this has regressed before (the
`--` inside a string-literal fix), so the edge cases are pinned here.
"""
from __future__ import annotations

from databricks_vision.backend.core._database import _split_sql_statements
from image_gen import _SCHEMA_SQL


def test_simple_statements():
    assert _split_sql_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_trailing_statement_without_semicolon():
    assert _split_sql_statements("SELECT 1;\nSELECT 2") == ["SELECT 1", "SELECT 2"]


def test_empty_statements_dropped():
    assert _split_sql_statements(" ;; \n ; SELECT 1 ;;") == ["SELECT 1"]


def test_semicolon_inside_string_literal_kept():
    assert _split_sql_statements("INSERT INTO t VALUES ('a;b'); SELECT 1;") == [
        "INSERT INTO t VALUES ('a;b')",
        "SELECT 1",
    ]


def test_escaped_quote_inside_string():
    sql = "INSERT INTO t VALUES ('it''s; fine'); SELECT 2;"
    assert _split_sql_statements(sql) == ["INSERT INTO t VALUES ('it''s; fine')", "SELECT 2"]


def test_line_comments_outside_strings_removed():
    sql = "-- header; with a semicolon\nSELECT 1; -- trailing; comment\nSELECT 2;"
    assert _split_sql_statements(sql) == ["SELECT 1", "SELECT 2"]


def test_double_dash_inside_string_preserved():
    sql = "INSERT INTO t VALUES ('keep -- this; text\n-- and this line');"
    assert _split_sql_statements(sql) == ["INSERT INTO t VALUES ('keep -- this; text\n-- and this line')"]


def test_schema_sql_splits_into_clean_statements():
    stmts = _split_sql_statements(_SCHEMA_SQL)
    assert len(stmts) > 30
    assert all(s.strip() == s and s for s in stmts)
    # Comments are stripped; no statement should start with a comment marker.
    assert not any(s.startswith("--") for s in stmts)
    # Extensions must come first: later DDL uses VECTOR and gen_random_uuid().
    assert stmts[0] == "CREATE EXTENSION IF NOT EXISTS vector"
    assert stmts[1] == "CREATE EXTENSION IF NOT EXISTS pgcrypto"
    # The eval_criteria seed (with a '' escape in "prompt''s") must survive as one statement.
    seeds = [s for s in stmts if s.startswith("INSERT INTO eval_criteria")]
    assert len(seeds) == 1 and "prompt''s" in seeds[0] and seeds[0].endswith("DO NOTHING")
