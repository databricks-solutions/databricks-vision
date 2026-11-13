"""Constants the React UI mirrors from the backend must not drift.

`ui/lib/image-models.ts` hard-codes a few backend values (its comments say "mirrors ...").
If one side changes without the other, the UI silently mislabels images or fallbacks.
"""
from __future__ import annotations

import re
from pathlib import Path

from databricks_vision.backend.routers.gallery import SINGLE_IMAGE_MODES
from image_gen import TRANSPARENT_FALLBACK_MODEL

IMAGE_MODELS_TS = (
    Path(__file__).resolve().parent.parent / "src" / "databricks_vision" / "ui" / "lib" / "image-models.ts"
).read_text()


def test_transparent_fallback_model_matches():
    m = re.search(r'export const TRANSPARENT_FALLBACK_MODEL = "([^"]+)"', IMAGE_MODELS_TS)
    assert m, "TRANSPARENT_FALLBACK_MODEL not found in image-models.ts"
    assert m.group(1) == TRANSPARENT_FALLBACK_MODEL


def test_single_image_modes_match():
    m = re.search(r"export const SINGLE_IMAGE_MODES = new Set\(\[([^\]]*)\]\)", IMAGE_MODELS_TS)
    assert m, "SINGLE_IMAGE_MODES not found in image-models.ts"
    ts_modes = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert ts_modes == set(SINGLE_IMAGE_MODES)
