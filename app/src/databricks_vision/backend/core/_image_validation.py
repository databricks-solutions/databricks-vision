"""Image-generation request validation shared by single-gen and batch routes.

Every rule is keyed off `image_gen.MODEL_PRESETS` so adding a model there is the only
change the backend needs.
"""
from __future__ import annotations

from fastapi import HTTPException

from image_gen import MODEL_PRESETS, enabled_image_models, resolve_image_model

_COMPLEXITIES = {"low", "medium", "high"}


def validate_tool_request(
    image_model: str, background: str, quality: str, size: str, complexity: str = "",
) -> str:
    """Validate one request's image-tool params; return the model that will serve it
    (`image_model`, or the transparent fallback when it can't render transparency).
    """
    effective = resolve_image_model(validate_image_model(image_model), background)
    validate_quality(effective, quality)
    validate_size(size, effective)
    validate_complexity(complexity)
    return effective


def validate_image_model(image_model: str) -> str:
    """Raise HTTPException(400) unless `image_model` is a known, enabled model."""
    if image_model not in enabled_image_models():
        raise HTTPException(
            400,
            f"Unknown image model {image_model!r}; available: {', '.join(enabled_image_models())}",
        )
    return image_model


def validate_quality(image_model: str, quality: str) -> None:
    """`image_model` is the resolved model (after any transparent fallback)."""
    allowed = MODEL_PRESETS[image_model]["qualities"]
    if quality not in allowed:
        raise HTTPException(
            400,
            f"Quality {quality!r} is not supported by {image_model} (allowed: {', '.join(allowed)})",
        )


def validate_complexity(complexity: str) -> None:
    if complexity and complexity not in _COMPLEXITIES:
        raise HTTPException(
            400, f"Invalid complexity {complexity!r}; expected one of low, medium, high"
        )


def validate_size(size: str, image_model: str) -> None:
    """Validate `size` against the resolved model's constraints.
    Raises HTTPException(400) on invalid input.

    Mirrors the client-side validation in routes/generate.tsx so a malformed
    `size` doesn't burn an OpenAI call.
    """
    if size == "auto":
        return

    fixed_sizes = MODEL_PRESETS[image_model]["sizes"]
    if fixed_sizes is not None:
        if size not in fixed_sizes:
            raise HTTPException(
                400,
                f"{image_model} does not support size {size!r} "
                f"(allowed: {', '.join(fixed_sizes)})",
            )
        return

    parts = size.split("x")
    if len(parts) != 2:
        raise HTTPException(400, f"Invalid size {size!r}; expected 'WxH' or 'auto'")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        raise HTTPException(400, f"Invalid size {size!r}; expected integer WxH")

    if w <= 0 or h <= 0:
        raise HTTPException(400, f"Both dimensions must be positive; got {w}x{h}")
    if w % 16 != 0 or h % 16 != 0:
        raise HTTPException(400, f"Both dimensions must be multiples of 16; got {w}x{h}")
    if max(w, h) > 3840:
        raise HTTPException(400, f"Maximum edge is 3840px; got {max(w, h)}")
    pixels = w * h
    if pixels < 655_360:
        raise HTTPException(400, f"Total pixels must be at least 655,360; got {pixels:,}")
    if pixels > 8_294_400:
        raise HTTPException(400, f"Total pixels must not exceed 8,294,400; got {pixels:,}")
    if max(w, h) / min(w, h) > 3.0:
        raise HTTPException(
            400,
            f"Long:short edge ratio must not exceed 3:1; got {max(w, h) / min(w, h):.2f}",
        )
