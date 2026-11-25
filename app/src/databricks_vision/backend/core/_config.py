from __future__ import annotations

import logging
from importlib import resources
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv
from image_gen import DEFAULT_IMAGE_MODEL, DEFAULT_LANGUAGE_MODEL
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..._metadata import app_name, app_slug

# --- Config ---

project_root = Path(__file__).parent.parent.parent.parent.parent
env_file = project_root / ".env"

if env_file.exists():
    load_dotenv(dotenv_path=env_file)


class AppConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=env_file,
        env_prefix=f"{app_slug.upper()}_",
        extra="ignore",
        env_nested_delimiter="__",
    )
    app_name: str = Field(default=app_name)

    # Databricks resources. catalog/schema_name MUST be supplied via the
    # DATABRICKS_VISION_CATALOG / DATABRICKS_VISION_SCHEMA_NAME env vars at
    # app start — there is no sensible default for a public release.
    catalog: str = Field(...)
    schema_name: str = Field(...)
    batch_gen_job_id: int = Field(default=0)

    # AI model settings
    # Defaults live in image_gen so the library, the app and the sync tests share them.
    model_name: str = Field(default=DEFAULT_LANGUAGE_MODEL)
    image_model: str = Field(default=DEFAULT_IMAGE_MODEL)
    embedding_endpoint: str = Field(default="siglip2-so400m-embeddings")
    default_quality: str = Field(default="auto")
    default_resolution: str = Field(default="1024x1024")
    default_input_fidelity: str = Field(default="high")
    default_output_format: str = Field(default="png")

    # MLflow GenAI evaluation. Judges score every generated image via make_judge
    # {{ trace }} judges (see backend/core/_eval.py). eval_experiment is injected at
    # deploy time (DATABRICKS_VISION_EVAL_EXPERIMENT); when empty, eval is skipped and
    # the app falls back to the plain structured analyzer output.
    eval_experiment: str = Field(default="")
    eval_enabled: bool = Field(default=True)
    # Judge model must be multimodal AND accept function tools with reasoning_effort='none'
    # on /v1/chat/completions (GPT-5.x and GPT-6.1 Terra do; GPT-6.1 Sol and GPT-6 Astra
    # reject 'none', so they can't judge). Defaults to databricks:/{model_name}, resolved at
    # startup, so a runtime Settings change to model_name doesn't move the judges.
    judge_model: str = Field(default="")
    judge_reasoning_effort: str = Field(default="none")
    # Images are downscaled to this max edge before becoming a trace attachment,
    # keeping them under MLflow's ~10MB attachment cap and cutting judge fetch cost.
    eval_image_max_px: int = Field(default=1024)

    @property
    def output_volume(self) -> str:
        return f"/Volumes/{self.catalog}/{self.schema_name}/generated_images"

    vision_volume: str = ""

    def model_post_init(self, __context):
        if not self.vision_volume:
            self.vision_volume = f"/Volumes/{self.catalog}/{self.schema_name}/vision_images"
        if not self.judge_model:
            self.judge_model = f"databricks:/{self.model_name}"

    @property
    def static_assets_path(self) -> Path:
        return Path(str(resources.files(app_slug))).joinpath("__dist__")

    def __hash__(self) -> int:
        return hash(self.app_name)


# --- Static assets dir ---
# The compiled frontend lives at <package>/__dist__. We derive this here rather than
# importing a `dist_dir` symbol from the apx-generated `_metadata.py` — newer apx versions
# no longer emit `dist_dir`, so deriving it keeps the app buildable across apx versions.
dist_dir = Path(str(resources.files(app_slug))).joinpath("__dist__")


# --- Logger ---

logger = logging.getLogger(app_name)
