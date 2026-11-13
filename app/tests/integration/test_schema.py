"""The production schema bootstraps cleanly (and idempotently) on Postgres + pgvector."""
from __future__ import annotations

import pytest

from databricks_vision.backend.core._eval import DEFAULT_CRITERIA, load_criteria
from image_gen import EMBEDDING_DIM
from tests.integration.conftest import apply_schema, execute, fetch

pytestmark = pytest.mark.integration

TABLES = {
    "batch_runs", "generated_images", "image_versions", "folders",
    "style_guidelines", "eval_criteria", "recipes",
}


def test_all_tables_exist(db):
    rows = fetch(db, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    assert TABLES <= {r["table_name"] for r in rows}


def test_extensions_installed(db):
    rows = fetch(db, "SELECT extname FROM pg_extension")
    assert {"vector", "pgcrypto"} <= {r["extname"] for r in rows}


def test_embedding_column_dimension_matches_library(db):
    rows = fetch(
        db,
        "SELECT format_type(atttypid, atttypmod) AS t FROM pg_attribute "
        "WHERE attrelid = 'generated_images'::regclass AND attname = 'embedding'",
    )
    assert rows[0]["t"] == f"vector({EMBEDDING_DIM})"


def test_indexes_exist(db):
    rows = fetch(db, "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
    defs = {r["indexname"]: r["indexdef"] for r in rows}
    assert "hnsw" in defs["idx_generated_images_embedding_hnsw"]
    assert "vector_cosine_ops" in defs["idx_generated_images_embedding_hnsw"]
    assert "gin" in defs["idx_generated_images_fts"].lower()
    assert "WHERE is_default" in defs["idx_style_guidelines_one_default"]


def test_migrated_columns_present(db):
    # Columns added by the ALTER TABLE ... ADD COLUMN IF NOT EXISTS migrations.
    rows = fetch(
        db,
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'",
    )
    cols = {(r["table_name"], r["column_name"]) for r in rows}
    for expected in [
        ("style_guidelines", "logo_path"), ("style_guidelines", "palette"), ("style_guidelines", "typography"),
        ("batch_runs", "background"), ("batch_runs", "style_guideline_id"), ("batch_runs", "image_model"),
        ("generated_images", "criteria_evaluation"), ("generated_images", "brand_conflicts"),
    ]:
        assert expected in cols, expected


def test_seeds_present(db):
    assert [r["name"] for r in fetch(db, "SELECT name FROM folders")] == ["default"]
    keys = [r["key"] for r in fetch(db, "SELECT key FROM eval_criteria ORDER BY sort_order")]
    assert keys == ["quality", "prompt", "text", "safe", "custom"]


def test_bootstrap_is_idempotent_and_preserves_data(db, bootstrapped_db_url):
    # Every app start re-runs the bootstrap; it must neither fail nor clobber edits.
    execute(db, "UPDATE eval_criteria SET instructions = 'edited {{ trace }}' WHERE key = 'quality'")
    execute(db, "INSERT INTO folders (name) VALUES ('kept')")
    apply_schema(bootstrapped_db_url)
    assert fetch(db, "SELECT instructions FROM eval_criteria WHERE key = 'quality'")[0]["instructions"] == "edited {{ trace }}"
    assert {r["name"] for r in fetch(db, "SELECT name FROM folders")} == {"default", "kept"}


def test_only_one_default_style_guideline_allowed(db):
    import psycopg

    execute(db, "INSERT INTO style_guidelines (name, is_default) VALUES ('a', TRUE)")
    with pytest.raises(psycopg.errors.UniqueViolation):
        execute(db, "INSERT INTO style_guidelines (name, is_default) VALUES ('b', TRUE)")


def test_seeded_criteria_match_default_criteria(db):
    """The SQL seed and _eval.DEFAULT_CRITERIA (used for reset-to-default) must not drift."""
    seeded = {r["key"]: r for r in load_criteria(db)}
    for default in DEFAULT_CRITERIA:
        row = seeded[default["key"]]
        assert row["label"] == default["label"]
        assert row["instructions"] == default["instructions"], default["key"]
        assert row["is_custom"] == default["is_custom"]
        assert row["enabled"] == default.get("enabled", True)


def test_load_criteria_reads_rows_by_column_name(db):
    """Regression: criteria loading broke when the pool's row factory changed (dict_row)."""
    execute(db, "UPDATE eval_criteria SET label = 'Brand fit', enabled = TRUE WHERE key = 'custom'")
    rows = load_criteria(db)
    assert [r["key"] for r in rows] == ["quality", "prompt", "text", "safe", "custom"]
    custom = rows[-1]
    assert custom == {**custom, "label": "Brand fit", "enabled": True, "is_custom": True}
