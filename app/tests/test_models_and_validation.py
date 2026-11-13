"""MODEL_PRESETS invariants and the request validators keyed off them.

These rules decide whether a request burns an image-model call, so a regression here either
rejects valid requests or lets malformed ones through to a paid API.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from databricks_vision.backend.core import _image_validation as v
from image_gen import (
    DEFAULT_IMAGE_MODEL,
    FORMAT_PRESETS,
    MODEL_PRESETS,
    TRANSPARENT_FALLBACK_MODEL,
    enabled_image_models,
    resolve_image_model,
)

FLEXIBLE_MODELS = [m for m in enabled_image_models() if MODEL_PRESETS[m]["sizes"] is None]
FIXED_MODELS = [m for m in enabled_image_models() if MODEL_PRESETS[m]["sizes"] is not None]

REQUIRED_KEYS = {
    "label", "description", "defaults", "qualities", "sizes", "supports_transparent",
    "supports_input_fidelity", "supports_complexity", "supports_svg", "enabled",
}


def _rejects(fn, *args) -> str:
    with pytest.raises(HTTPException) as exc:
        fn(*args)
    assert exc.value.status_code == 400
    return str(exc.value.detail)


# --- MODEL_PRESETS ----------------------------------------------------------------------


@pytest.mark.parametrize("model_id", list(MODEL_PRESETS))
def test_preset_has_every_capability_key(model_id):
    assert REQUIRED_KEYS <= set(MODEL_PRESETS[model_id]), model_id


@pytest.mark.parametrize("model_id", list(MODEL_PRESETS))
def test_preset_defaults_are_themselves_valid(model_id):
    preset = MODEL_PRESETS[model_id]
    assert preset["defaults"]["quality"] in preset["qualities"]
    if preset["enabled"]:
        v.validate_size(preset["defaults"]["size"], model_id)


def test_default_and_fallback_models_are_enabled_and_capable():
    assert DEFAULT_IMAGE_MODEL in enabled_image_models()
    assert TRANSPARENT_FALLBACK_MODEL in enabled_image_models()
    assert MODEL_PRESETS[TRANSPARENT_FALLBACK_MODEL]["supports_transparent"]


def test_enabled_image_models_preserves_display_order():
    assert enabled_image_models() == [m for m, p in MODEL_PRESETS.items() if p["enabled"]]


@pytest.mark.parametrize("model_id", enabled_image_models())
def test_resolve_image_model(model_id):
    assert resolve_image_model(model_id) == model_id
    assert resolve_image_model(model_id, "opaque") == model_id
    expected = model_id if MODEL_PRESETS[model_id]["supports_transparent"] else TRANSPARENT_FALLBACK_MODEL
    assert resolve_image_model(model_id, "transparent") == expected


@pytest.mark.parametrize("fmt_key", list(FORMAT_PRESETS))
@pytest.mark.parametrize("model_id", FLEXIBLE_MODELS)
def test_every_marketing_format_is_valid_for_flexible_models(fmt_key, model_id):
    # Compose / Adapt send these sizes verbatim; one bad preset would 400 every request for it.
    v.validate_size(FORMAT_PRESETS[fmt_key]["size"], model_id)


# --- validate_image_model / quality / complexity / raster format -------------------------


def test_validate_image_model():
    assert v.validate_image_model(DEFAULT_IMAGE_MODEL) == DEFAULT_IMAGE_MODEL
    assert "Unknown image model" in _rejects(v.validate_image_model, "dall-e-9")


@pytest.mark.parametrize("model_id", enabled_image_models())
def test_validate_quality(model_id):
    for quality in MODEL_PRESETS[model_id]["qualities"]:
        v.validate_quality(model_id, quality)
    _rejects(v.validate_quality, model_id, "ultra")


def test_extended_qualities_only_on_models_that_support_them():
    assert "xhigh" in MODEL_PRESETS["gpt-image-2.5-flare"]["qualities"]
    v.validate_quality("gpt-image-2.5-flare", "xhigh")
    assert "xhigh" not in MODEL_PRESETS["gpt-image-1.5"]["qualities"]
    _rejects(v.validate_quality, "gpt-image-1.5", "xhigh")


@pytest.mark.parametrize("complexity", ["", "low", "medium", "high"])
def test_validate_complexity_accepts(complexity):
    v.validate_complexity(complexity)


def test_validate_complexity_rejects():
    _rejects(v.validate_complexity, "extreme")


@pytest.mark.parametrize("fmt", ["png", "jpeg", "webp"])
def test_raster_formats_accepted(fmt):
    v.validate_raster_format(fmt)


def test_svg_is_not_a_raster_format():
    assert "/api/generate-svg" in _rejects(v.validate_raster_format, "svg")


# --- validate_size ----------------------------------------------------------------------


@pytest.mark.parametrize("size", ["auto", "1024x1024", "1536x1024", "2048x1152", "3840x2160", "2160x3840", "2304x768"])
@pytest.mark.parametrize("model_id", FLEXIBLE_MODELS)
def test_flexible_sizes_accepted(model_id, size):
    v.validate_size(size, model_id)


@pytest.mark.parametrize(
    ("size", "reason"),
    [
        ("1024", "expected 'WxH'"),
        ("axb", "integer WxH"),
        ("0x1024", "positive"),
        ("1000x1000", "multiples of 16"),
        ("4096x1024", "Maximum edge"),
        ("512x512", "at least 655,360"),
        ("3840x3840", "must not exceed"),
        ("2400x768", "3:1"),
    ],
)
@pytest.mark.parametrize("model_id", FLEXIBLE_MODELS)
def test_flexible_sizes_rejected(model_id, size, reason):
    assert reason in _rejects(v.validate_size, size, model_id)


def test_pixel_ceiling():
    # 3840x2176 is within the max edge and multiples of 16, but over 8,294,400 pixels.
    assert "must not exceed" in _rejects(v.validate_size, "3840x2176", FLEXIBLE_MODELS[0])


@pytest.mark.parametrize("model_id", FIXED_MODELS)
def test_fixed_size_models_only_accept_their_sizes(model_id):
    for size in MODEL_PRESETS[model_id]["sizes"]:
        v.validate_size(size, model_id)
    assert "does not support size" in _rejects(v.validate_size, "2048x1152", model_id)


def test_validate_tool_request_returns_transparent_fallback():
    # gpt-image-2 can't render transparency, so a transparent request is served by the fallback.
    assert v.validate_tool_request("gpt-image-2", "transparent", "auto", "1024x1024") == TRANSPARENT_FALLBACK_MODEL
    assert v.validate_tool_request("gpt-image-2", "opaque", "auto", "1024x1024") == "gpt-image-2"


def test_validate_tool_request_checks_size_against_the_effective_model():
    # gpt-image-2 accepts 2048x1152, but the transparent fallback (fixed sizes) does not.
    v.validate_size("2048x1152", "gpt-image-2")
    _rejects(v.validate_tool_request, "gpt-image-2", "transparent", "auto", "2048x1152")
