"""Runtime settings management."""
from fastapi import APIRouter, Request
from image_gen import FORMAT_PRESETS, MODEL_PRESETS, enabled_image_models

from ..core._image_validation import validate_image_model
from ..models import FormatPresetOut, ImageModelOut, SettingsOut, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut, operation_id="getSettings")
def get_settings(request: Request):
    cfg = request.app.state.config
    return SettingsOut(
        model_name=cfg.model_name,
        image_model=cfg.image_model,
        default_quality=cfg.default_quality,
        default_resolution=cfg.default_resolution,
        default_input_fidelity=cfg.default_input_fidelity,
        default_output_format=cfg.default_output_format,
        vision_volume=cfg.vision_volume,
    )


@router.get("/image-models", response_model=list[ImageModelOut], operation_id="listImageModels")
def list_image_models():
    """Image models the app can generate with, and what each supports (drives the UI pickers)."""
    models = []
    for model_id in enabled_image_models():
        preset = MODEL_PRESETS[model_id]
        models.append(ImageModelOut(
            id=model_id,
            label=preset["label"],
            description=preset["description"],
            qualities=list(preset["qualities"]),
            sizes=list(preset["sizes"]) if preset["sizes"] else None,
            supports_transparent=preset["supports_transparent"],
            supports_complexity=preset["supports_complexity"],
            supports_svg=preset["supports_svg"],
        ))
    return models


@router.get("/formats", response_model=list[FormatPresetOut], operation_id="listFormatPresets")
def list_format_presets():
    """Marketing formats offered by Compose and Adapt-to-formats."""
    return [FormatPresetOut(key=key, **preset) for key, preset in FORMAT_PRESETS.items()]


@router.put("", response_model=SettingsOut, operation_id="updateSettings")
def update_settings(body: SettingsUpdate, request: Request):
    # Settings live on this worker's in-memory config — they reset on restart and aren't
    # shared across uvicorn workers. The Generate page sends image_model per request, so
    # the image_model here is only the default for callers that don't.
    cfg = request.app.state.config

    if body.model_name is not None:
        cfg.model_name = body.model_name
    if body.image_model is not None:
        cfg.image_model = validate_image_model(body.image_model)
    if body.default_quality is not None:
        cfg.default_quality = body.default_quality
    if body.default_resolution is not None:
        cfg.default_resolution = body.default_resolution
    if body.default_input_fidelity is not None:
        cfg.default_input_fidelity = body.default_input_fidelity
    if body.default_output_format is not None:
        cfg.default_output_format = body.default_output_format
    if body.vision_volume is not None:
        cfg.vision_volume = body.vision_volume

    return SettingsOut(
        model_name=cfg.model_name,
        image_model=cfg.image_model,
        default_quality=cfg.default_quality,
        default_resolution=cfg.default_resolution,
        default_input_fidelity=cfg.default_input_fidelity,
        default_output_format=cfg.default_output_format,
        vision_volume=cfg.vision_volume,
    )
