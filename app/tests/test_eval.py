"""MLflow judge construction (offline — make_judge only validates the template, no model call)."""
from __future__ import annotations

import pytest

from databricks_vision.backend.core import _eval
from databricks_vision.backend.core._eval import (
    DEFAULT_CRITERIA,
    build_judges,
    load_criteria,
    validate_criterion_instructions,
)

MODEL = "databricks:/databricks-gpt-5-5"
VALID = "Score the image in {{ trace }} from 0-5 with a one-sentence rationale."


@pytest.mark.parametrize("bad", [None, "", "   \n "])
def test_empty_instructions_rejected(bad):
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_criterion_instructions(bad, MODEL, "none")


def test_instructions_without_trace_placeholder_rejected():
    # make_judge would accept {{ inputs }} alone, but then the judge scores the image blind.
    with pytest.raises(ValueError, match=r"\{\{ trace \}\}"):
        validate_criterion_instructions("Rate {{ inputs }} from 0-5", MODEL, "none")


@pytest.mark.parametrize("instructions", [VALID, "Score {{trace}} 0-5"])
def test_valid_instructions_accepted(instructions):
    validate_criterion_instructions(instructions, MODEL, "none")


def test_default_criteria_shape():
    assert [c["key"] for c in DEFAULT_CRITERIA] == ["quality", "prompt", "text", "safe", "custom"]
    for c in DEFAULT_CRITERIA:
        validate_criterion_instructions(c["instructions"], MODEL, "none")
    assert DEFAULT_CRITERIA[-1]["is_custom"] and DEFAULT_CRITERIA[-1]["enabled"] is False


def test_load_criteria_without_pool_falls_back_to_defaults():
    rows = load_criteria(None)
    assert [r["key"] for r in rows] == [c["key"] for c in DEFAULT_CRITERIA]
    assert {r["key"]: r["enabled"] for r in rows}["custom"] is False
    assert all("enabled" in r for r in rows)


def test_build_judges_skips_disabled_criteria():
    criteria = [{**c, "enabled": c.get("enabled", True)} for c in DEFAULT_CRITERIA]
    judges = build_judges(MODEL, "none", criteria)
    assert set(judges) == {"quality", "prompt", "text", "safe", "brand_conflict", "criteria_adherence"}


def test_one_bad_criterion_drops_only_its_own_judge(monkeypatch):
    """Regression: a single bad criterion used to take down the whole judge set."""
    real_make_judge = _eval._make_judge

    def flaky_make_judge(name, instructions, value_type, model, reasoning_effort):
        if name == "text":
            raise ValueError("broken template")
        return real_make_judge(name, instructions, value_type, model, reasoning_effort)

    monkeypatch.setattr(_eval, "_make_judge", flaky_make_judge)
    criteria = [{**c, "enabled": True} for c in DEFAULT_CRITERIA]
    judges = build_judges(MODEL, "none", criteria)
    assert "text" not in judges
    assert {"quality", "prompt", "safe", "custom", "brand_conflict", "criteria_adherence"} <= set(judges)
