"""Image-generation size validation shared by single-gen and batch routes."""
from __future__ import annotations

from fastapi import HTTPException

# Sizes supported by gpt-image-1.5 (used when transparent BG is requested,
# since the lib auto-routes transparent → gpt-image-1.5).
_GPT_IMAGE_15_SIZES = {"auto", "1024x1024", "1024x1536", "1536x1024"}


def validate_size(size: str, transparent: bool) -> None:
    """Validate `size` against gpt-image-2 / gpt-image-1.5 (transparent) constraints.
    Raises HTTPException(400) on invalid input.

    Mirrors the client-side validation in routes/generate.tsx so a malformed
    `size` doesn't burn an OpenAI call.
    """
    if size == "auto":
        return

    if transparent:
        if size not in _GPT_IMAGE_15_SIZES:
            raise HTTPException(
                400,
                f"Transparent BG uses gpt-image-1.5 — size {size!r} is not supported "
                "(allowed: 1024x1024, 1024x1536, 1536x1024, auto)",
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
