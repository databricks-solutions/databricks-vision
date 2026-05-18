from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from .. import __version__


class VersionOut(BaseModel):
    version: str

    @classmethod
    def from_metadata(cls):
        return cls(version=__version__)


# --- Batch models ---

class VariationItem(BaseModel):
    label: str
    prompt: str


class BatchCreate(BaseModel):
    batch_name: str = ""
    batch_mode: str = "multi_image"
    input_volume_path: str = ""
    source_image_path: str = ""
    reference_image_path: str = ""
    prompt_template: str = ""
    size: str = "1024x1024"
    quality: str = "low"
    image_model: str = "gpt-image-2"
    output_format: str = "png"
    background: str = "opaque"
    style_guideline_id: int | None = None
    variations: list[VariationItem] = []


class BatchRunOut(BaseModel):
    batch_id: str
    batch_name: str | None = None
    batch_mode: str = "multi_image"
    input_volume_path: str
    source_image_path: str | None = None
    reference_image_path: str | None = None
    prompt_template: str | None = None
    size: str | None = None
    quality: str | None = None
    image_model: str | None = None
    output_format: str | None = None
    background: str | None = None
    style_guideline_id: int | None = None
    status: str
    created_at: datetime | None = None
    created_by: str | None = None
    job_run_id: int | None = None
    total_images: int | None = None
    successful_images: int | None = None
    output_volume_path: str | None = None
    folder: str = "default"


class GeneratedImageOut(BaseModel):
    id: int | None = None
    batch_id: str
    image_name: str | None = None
    prompt: str | None = None
    status: str | None = None
    error_message: str | None = None
    volume_path: str | None = None
    variation_label: str | None = None
    input_image_path: str | None = None
    version_count: int = 0
    description: str | None = None
    tags: list[str] = []
    folder: str | None = None
    thumbnail_path: str | None = None
    # Eval fields populated by ImageAnalyzer (structured output).
    evaluation: str | None = None
    metrics: dict | None = None
    missing_elements: list[str] = []
    safety_flags: list[str] = []
    brand_conflicts: list[str] = []
    improved_prompt: str | None = None
    criteria_evaluation: str | None = None


class ImageVersionOut(BaseModel):
    version_id: int
    batch_id: str
    image_id: int
    version: int
    prompt: str
    status: str | None = None
    error_message: str | None = None
    volume_path: str | None = None
    created_at: datetime | None = None


class RegenerateRequest(BaseModel):
    prompt: str
    use_source: bool = False


class RegenerateResponse(BaseModel):
    image: GeneratedImageOut
    version: ImageVersionOut


class SearchResultItem(BaseModel):
    batch_id: str
    image_id: int
    image_name: str | None = None
    prompt: str | None = None
    volume_path: str | None = None
    variation_label: str | None = None
    batch_name: str | None = None
    batch_mode: str | None = None
    description: str | None = None
    tags: list[str] = []
    thumbnail_path: str | None = None
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str


class BatchDetailOut(BaseModel):
    batch: BatchRunOut
    images: list[GeneratedImageOut]



class FolderOut(BaseModel):
    id: UUID
    name: str
    image_count: int = 0
    created_at: datetime | None = None


class FolderCreate(BaseModel):
    name: str


# --- Style guidelines (named analyzer criteria) ---

class StyleGuidelineOut(BaseModel):
    id: int
    name: str
    body: str
    is_default: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StyleGuidelineCreate(BaseModel):
    name: str
    body: str = ""
    is_default: bool = False


class StyleGuidelineUpdate(BaseModel):
    name: str | None = None
    body: str | None = None
    is_default: bool | None = None


# --- Settings models ---

class SettingsOut(BaseModel):
    model_name: str
    image_model: str
    default_quality: str
    default_resolution: str
    default_input_fidelity: str
    default_output_format: str
    vision_volume: str


class SettingsUpdate(BaseModel):
    model_name: str | None = None
    image_model: str | None = None
    default_quality: str | None = None
    default_resolution: str | None = None
    default_input_fidelity: str | None = None
    default_output_format: str | None = None
    vision_volume: str | None = None


# --- Volume browser models ---

class CatalogOut(BaseModel):
    name: str
    comment: str | None = None


class SchemaOut(BaseModel):
    name: str
    comment: str | None = None


class VolumeOut(BaseModel):
    name: str
    full_name: str
    volume_type: str | None = None


class FileEntryOut(BaseModel):
    name: str
    path: str
    is_directory: bool
    file_size: int | None = None


# --- App config ---

class AppConfigOut(BaseModel):
    workspace_url: str
    org_id: str = ""
