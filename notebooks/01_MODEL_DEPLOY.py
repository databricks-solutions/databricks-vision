# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Image Generator Model Deploy
# MAGIC
# MAGIC Logs the `ImageGenerator` pyfunc model to MLflow, registers it in Unity Catalog,
# MAGIC and deploys it as a Model Serving endpoint. This endpoint wraps the Responses API
# MAGIC (gpt-5.2 + gpt-image-2 / gpt-image-1.5) so it can be called via `ai_query()` for batch inference.

# COMMAND ----------

# MAGIC %pip install pillow databricks-openai
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import json
import mlflow
import pandas as pd
import requests
from config import (
    ENDPOINT_NAME,
    UC_MODEL_NAME,
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Define the pyfunc model
# MAGIC
# MAGIC The model class lives in `image_gen_model.py` alongside this notebook.
# MAGIC We import it here for local testing, then log it using "models from code"
# MAGIC (the file has `mlflow.models.set_model()` at the bottom).

# COMMAND ----------

from image_gen_model import ImageGenerator

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create model signature

# COMMAND ----------

from mlflow.models.signature import ModelSignature
from mlflow.types.schema import ColSpec, Schema

input_schema = Schema(
    [
        ColSpec("string", "input_image_b64"),
        ColSpec("string", "reference_image_b64"),
        ColSpec("string", "prompt"),
        # Optional per-row tool params; the pyfunc falls back to module defaults
        # when these are NaN/empty. Adding new ColSpecs at the end keeps the
        # signature backwards compatible with callers that don't pass them.
        ColSpec("string", "size", required=False),
        ColSpec("string", "quality", required=False),
        ColSpec("string", "image_model", required=False),
        ColSpec("string", "output_format", required=False),
        ColSpec("string", "background", required=False),
    ]
)

output_schema = Schema(
    [
        ColSpec("string", "output_image_b64"),
        ColSpec("string", "status"),
    ]
)

signature = ModelSignature(inputs=input_schema, outputs=output_schema)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test locally before logging
# MAGIC
# MAGIC Quick sanity check with a synthetic single-row input. Exercises the full
# MAGIC signature (including the optional tool-param columns) before the expensive
# MAGIC `log_model` + endpoint deploy steps.

# COMMAND ----------

import os

# Set env vars for local test (on Model Serving these are injected automatically)
token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
host = f"https://{spark.conf.get('spark.databricks.workspaceUrl')}"
os.environ["DATABRICKS_TOKEN"] = token
os.environ["DATABRICKS_HOST"] = host

# COMMAND ----------

# Synthetic single-row input. The pyfunc is edit-mode (requires input_image_b64),
# so we feed it a tiny solid-grey PNG; the prompt instructs the model to replace it.
# This burns one image generation API call but validates the full code path before
# the (slower) endpoint deploy.
import base64
from io import BytesIO
from PIL import Image

_buf = BytesIO()
Image.new("RGB", (256, 256), color=(128, 128, 128)).save(_buf, format="PNG")
_synthetic_input = base64.b64encode(_buf.getvalue()).decode()

sample = pd.DataFrame([{
    "input_image_b64": _synthetic_input,
    "reference_image_b64": "",
    "prompt": "Replace this image with a red apple on a clean white background, studio photography",
    "size": "1024x1024",
    "quality": "low",
    "image_model": "gpt-image-2",
    "output_format": "png",
    "background": "opaque",
}])

print(f"Testing with prompt: {sample['prompt'].iloc[0][:100]}...")

# COMMAND ----------

# Local test
model = ImageGenerator()
model.load_context(context=None)
result = model.predict(context=None, model_input=sample)
print(f"Status: {result['status'].iloc[0]}")
if result["output_image_b64"].iloc[0]:
    print(f"Generated image: {len(result['output_image_b64'].iloc[0])} chars base64")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Display test result

# COMMAND ----------

import base64
from io import BytesIO
from PIL import Image

if result["output_image_b64"].iloc[0]:
    img_bytes = base64.b64decode(result["output_image_b64"].iloc[0])
    img = Image.open(BytesIO(img_bytes))
    display(img)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log model to MLflow

# COMMAND ----------

pip_requirements = [
    "pillow",
    "databricks-openai",  # Auto-auth via DatabricksOpenAI client
]

# COMMAND ----------

from mlflow.models.resources import DatabricksServingEndpoint

resources = [
    DatabricksServingEndpoint(endpoint_name="databricks-gpt-5-5"),
]

mlflow.set_registry_uri("databricks-uc")

with mlflow.start_run(run_name="image_generator") as run:
    mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model="image_gen_model.py",
        signature=signature,
        pip_requirements=pip_requirements,
        resources=resources,
        registered_model_name=UC_MODEL_NAME,
    )

run_id = run.info.run_id
print(f"Model logged: run_id={run_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Get latest model version

# COMMAND ----------

client = mlflow.tracking.MlflowClient()
model_version_infos = client.search_model_versions(f"name = '{UC_MODEL_NAME}'")
model_version = max(int(mv.version) for mv in model_version_infos)
print(f"Latest model version: {model_version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy serving endpoint

# COMMAND ----------

notebook_token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
workspace_url = f"https://{spark.conf.get('spark.databricks.workspaceUrl')}"

headers = {
    "Authorization": f"Bearer {notebook_token}",
    "Content-Type": "application/json",
}

# Check if endpoint already exists
existing = requests.get(
    f"{workspace_url}/api/2.0/serving-endpoints/{ENDPOINT_NAME}",
    headers=headers,
)

# DatabricksServingEndpoint resource declaration auto-injects M2M OAuth credentials.
payload = {
    "served_entities": [
        {
            "name": ENDPOINT_NAME,
            "entity_name": UC_MODEL_NAME,
            "entity_version": model_version,
            "workload_size": "Medium",
            "scale_to_zero_enabled": True,
            "workload_type": "CPU",
        }
    ],
}

if existing.status_code == 200:
    # Update existing endpoint
    response = requests.put(
        f"{workspace_url}/api/2.0/serving-endpoints/{ENDPOINT_NAME}/config",
        headers=headers,
        data=json.dumps(payload),
    )
    print(f"Endpoint updated: {response.status_code}")
else:
    # Create new endpoint
    create_payload = {"name": ENDPOINT_NAME, "config": payload}
    response = requests.post(
        f"{workspace_url}/api/2.0/serving-endpoints",
        headers=headers,
        data=json.dumps(create_payload),
    )
    print(f"Endpoint created: {response.status_code}")

print(response.json())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Wait for endpoint to be ready
# MAGIC
# MAGIC The endpoint may take a few minutes to provision. Monitor status below.

# COMMAND ----------

import time

for i in range(60):
    status = requests.get(
        f"{workspace_url}/api/2.0/serving-endpoints/{ENDPOINT_NAME}",
        headers=headers,
    ).json()
    state = status.get("state", {}).get("ready", "UNKNOWN")
    config_state = status.get("state", {}).get("config_update", "UNKNOWN")
    print(f"[{i}] ready={state}, config_update={config_state}")
    if state == "READY" and config_state == "NOT_UPDATING":
        print("✓ Endpoint is ready!")
        break
    time.sleep(30)
else:
    print("⚠ Endpoint did not become ready within 30 minutes. Check the Serving UI.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test the deployed endpoint

# COMMAND ----------

from mlflow.deployments import get_deploy_client

deploy_client = get_deploy_client("databricks")

test_payload = {
    "dataframe_split": {
        "columns": [
            "input_image_b64", "reference_image_b64", "prompt",
            "size", "quality", "image_model", "output_format", "background",
        ],
        "data": [sample.iloc[0].tolist()],
    }
}

endpoint_result = deploy_client.predict(endpoint=ENDPOINT_NAME, inputs=test_payload)
print(f"Endpoint test result: {endpoint_result}")
