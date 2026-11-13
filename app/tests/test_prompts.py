"""Pure helpers in routers/generate.py that shape filenames and the Compose instruction."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from databricks_vision.backend.models import StyleGuidelineOut
from databricks_vision.backend.routers.generate import (
    _compose_prompt,
    _format_preset,
    _parse_brand_kit_id,
    _slug_from_prompt,
)
from image_gen import FORMAT_PRESETS


@pytest.mark.parametrize(
    ("prompt", "slug"),
    [
        ("A Red Fox in the snow, at dusk", "a_red_fox_in"),
        ("  Café  ☕  latte!!  ", "caf_latte"),
        ("!!!", "image"),
        ("", "image"),
        ("x" * 100, "x" * 40),
    ],
)
def test_slug_from_prompt(prompt, slug):
    assert _slug_from_prompt(prompt) == slug


def test_slug_is_filename_safe():
    slug = _slug_from_prompt("../../etc/passwd; rm -rf / && echo $HOME")
    assert slug and all(c.isalnum() or c == "_" for c in slug)


def test_format_preset():
    assert _format_preset("story") == FORMAT_PRESETS["story"]
    with pytest.raises(HTTPException) as exc:
        _format_preset("billboard")
    assert exc.value.status_code == 400


@pytest.mark.parametrize(("raw", "expected"), [("", None), ("   ", None), ("7", 7)])
def test_parse_brand_kit_id(raw, expected):
    assert _parse_brand_kit_id(raw) == expected


def test_parse_brand_kit_id_rejects_non_integers():
    with pytest.raises(HTTPException) as exc:
        _parse_brand_kit_id("seven")
    assert exc.value.status_code == 400


def _kit(**overrides) -> StyleGuidelineOut:
    base = dict(id=1, name="Acme", body="", is_default=False, palette=[], typography="")
    return StyleGuidelineOut(**{**base, **overrides})


def test_compose_prompt_with_copy_and_brand_kit():
    prompt = _compose_prompt(
        FORMAT_PRESETS["landscape"],
        headline="Summer Sale",
        subheadline="  Up to 50% off  ",
        cta="Shop now",
        art_direction="bright, airy",
        kit=_kit(palette=["#FF0000", "#00FF00"], typography="Inter Bold"),
    )
    assert "2048×1152, 16:9" in prompt
    assert '- Headline: "Summer Sale"' in prompt
    assert '- Subheadline: "Up to 50% off"' in prompt  # copy is stripped
    assert '- Call to action (styled as a button): "Shop now"' in prompt
    assert "Brand colours: #FF0000, #00FF00" in prompt
    assert "Typography: Inter Bold" in prompt
    assert "Art direction: bright, airy" in prompt
    assert prompt.rstrip().endswith("Never crop or overlap text, logo or product.")


def test_compose_prompt_without_copy_forbids_new_text():
    prompt = _compose_prompt(
        FORMAT_PRESETS["square"], headline="", subheadline=" ", cta="", art_direction="", kit=None,
    )
    assert "Do not add any text" in prompt
    assert "Headline" not in prompt
    assert "Brand colours" not in prompt
    assert "Art direction" not in prompt
