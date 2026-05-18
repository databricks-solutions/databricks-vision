"""Runtime settings management."""
from fastapi import APIRouter, Request

from ..models import SettingsOut, SettingsUpdate

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


@router.put("", response_model=SettingsOut, operation_id="updateSettings")
def update_settings(body: SettingsUpdate, request: Request):
    cfg = request.app.state.config
    image_gen = getattr(request.app.state, "image_gen", None)

    if body.model_name is not None:
        cfg.model_name = body.model_name
        if image_gen:
            image_gen.model = body.model_name
    if body.image_model is not None:
        cfg.image_model = body.image_model
        if image_gen:
            image_gen.DEFAULT_TOOLS["model"] = body.image_model
    if body.default_quality is not None:
        cfg.default_quality = body.default_quality
        if image_gen:
            image_gen.DEFAULT_TOOLS["quality"] = body.default_quality
    if body.default_resolution is not None:
        cfg.default_resolution = body.default_resolution
        if image_gen:
            image_gen.DEFAULT_TOOLS["size"] = body.default_resolution
    if body.default_input_fidelity is not None:
        cfg.default_input_fidelity = body.default_input_fidelity
    if body.default_output_format is not None:
        cfg.default_output_format = body.default_output_format
        if image_gen:
            image_gen.DEFAULT_TOOLS["output_format"] = body.default_output_format
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
