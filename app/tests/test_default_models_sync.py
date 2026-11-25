"""The default image and language models are repeated where `image_gen` can't be imported.

`image_gen.DEFAULT_IMAGE_MODEL` / `DEFAULT_LANGUAGE_MODEL` are the source of truth (the app's
AppConfig reads them). The batch serving endpoint, the batch notebook, the bundle's job
parameter and the Settings dropdown hard-code copies; a missed copy silently runs the old model.
"""
from __future__ import annotations

import re
from pathlib import Path

from databricks_vision.backend.core._config import AppConfig
from image_gen import DEFAULT_IMAGE_MODEL, DEFAULT_LANGUAGE_MODEL

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NOTEBOOKS = REPO_ROOT / "notebooks"
SETTINGS_TSX = (
    REPO_ROOT / "app" / "src" / "databricks_vision" / "ui" / "routes" / "settings.tsx"
).read_text()


def _constant(text: str, name: str) -> str:
    m = re.search(rf'^{name} = "([^"]+)"', text, re.MULTILINE)
    assert m, f"{name} not found"
    return m.group(1)


def test_app_config_uses_image_gen_defaults():
    fields = AppConfig.model_fields
    assert fields["image_model"].default == DEFAULT_IMAGE_MODEL
    assert fields["model_name"].default == DEFAULT_LANGUAGE_MODEL


def test_serving_endpoint_module_matches():
    text = (NOTEBOOKS / "image_gen_model.py").read_text()
    assert _constant(text, "DEFAULT_IMAGE_MODEL") == DEFAULT_IMAGE_MODEL
    assert _constant(text, "LLM_MODEL") == DEFAULT_LANGUAGE_MODEL


def test_model_deploy_grants_the_language_model():
    text = (NOTEBOOKS / "01_MODEL_DEPLOY.py").read_text()
    endpoints = re.findall(r'DatabricksServingEndpoint\(endpoint_name="([^"]+)"\)', text)
    assert DEFAULT_LANGUAGE_MODEL in endpoints


def test_batch_notebook_and_job_default_to_the_image_model():
    notebook = (NOTEBOOKS / "02_BATCH_GENERATE.py").read_text()
    assert f'dbutils.widgets.text("image_model", "{DEFAULT_IMAGE_MODEL}"' in notebook
    assert f'dbutils.widgets.get("image_model") or "{DEFAULT_IMAGE_MODEL}"' in notebook

    bundle = (REPO_ROOT / "databricks.yml").read_text()
    m = re.search(r'- name: image_model\s+default: "([^"]+)"', bundle)
    assert m, "batch job image_model parameter not found in databricks.yml"
    assert m.group(1) == DEFAULT_IMAGE_MODEL


def test_settings_dropdown_offers_the_language_model():
    assert f'<SelectItem value="{DEFAULT_LANGUAGE_MODEL}">' in SETTINGS_TSX
