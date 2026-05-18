# Databricks notebook source
# MAGIC %md
# MAGIC # 00 — SigLIP 2 Image Embedding Model Deploy
# MAGIC
# MAGIC Downloads SigLIP 2 SO400M/14-384 from Hugging Face, wraps it as an MLflow PyFunc
# MAGIC that accepts both text and base64-encoded image inputs, registers it in Unity
# MAGIC Catalog, and deploys it as a GPU Model Serving endpoint.
# MAGIC
# MAGIC SigLIP 2 produces 1152-dimensional embeddings in a shared text/image vector space —
# MAGIC used by the Databricks Vision app for semantic gallery search.
# MAGIC
# MAGIC Run this notebook once per workspace before deploying the app for the first time
# MAGIC (or after the existing endpoint is decommissioned). Endpoint provisioning takes
# MAGIC roughly 30 minutes; idempotent on re-run.
# MAGIC
# MAGIC Reference: [SigLIP 2 paper](https://arxiv.org/abs/2502.14786)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters
# MAGIC
# MAGIC Override these in the workspace UI (Widgets panel) or via job parameters.
# MAGIC `catalog` and `schema` have no default — supply them before running.

# COMMAND ----------

dbutils.widgets.text("catalog", "", "Catalog")
dbutils.widgets.text("schema", "", "Schema")
dbutils.widgets.text("endpoint_name", "siglip2-so400m-embeddings", "Endpoint Name")
dbutils.widgets.text("hf_model_id", "google/siglip2-so400m-patch14-384", "HF Model ID")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
endpoint_name = dbutils.widgets.get("endpoint_name")
hf_model_id = dbutils.widgets.get("hf_model_id")

model_name = "siglip2_so400m_embeddings"
registered_model_name = f"{catalog}.{schema}.{model_name}"

print(f"Catalog/schema:     {catalog}.{schema}")
print(f"Registered model:   {registered_model_name}")
print(f"Endpoint:           {endpoint_name}")
print(f"HF model:           {hf_model_id}")

# COMMAND ----------

# MAGIC %pip install --upgrade transformers torch pillow mlflow databricks-sdk sentencepiece protobuf
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# Re-read widgets — restartPython clears state
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
endpoint_name = dbutils.widgets.get("endpoint_name")
hf_model_id = dbutils.widgets.get("hf_model_id")
model_name = "siglip2_so400m_embeddings"
registered_model_name = f"{catalog}.{schema}.{model_name}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Smoke-test the model locally before logging it

# COMMAND ----------

import torch
import numpy as np
from PIL import Image
from transformers import AutoModel, AutoProcessor


def to_tensor(output):
    """Extract embedding tensor from model output."""
    if isinstance(output, torch.Tensor):
        return output
    return output.pooler_output


print(f"Downloading {hf_model_id}...")
model = AutoModel.from_pretrained(hf_model_id)
processor = AutoProcessor.from_pretrained(hf_model_id)

device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)
model.eval()
print(f"Model loaded on device: {device}")
print(f"Model parameters: {sum(p.numel() for p in model.parameters()) / 1e6:.0f}M")

# COMMAND ----------

test_text = "a photo of a cat sitting on a couch"
text_inputs = processor(text=[test_text], return_tensors="pt", padding="max_length").to(device)

with torch.no_grad():
    text_emb = to_tensor(model.get_text_features(**text_inputs))
text_emb = text_emb / text_emb.norm(dim=-1, keepdim=True)
print(f"Text embedding shape: {text_emb.shape}")

test_image = Image.fromarray(np.random.randint(0, 255, (384, 384, 3), dtype=np.uint8))
image_inputs = processor(images=test_image, return_tensors="pt").to(device)

with torch.no_grad():
    image_emb = to_tensor(model.get_image_features(**image_inputs))
image_emb = image_emb / image_emb.norm(dim=-1, keepdim=True)
print(f"Image embedding shape: {image_emb.shape}")

cosine_sim = (text_emb @ image_emb.T).item()
print(f"Cosine similarity (text vs random image): {cosine_sim:.4f}  (low expected — random noise)")

del model, processor
if torch.cuda.is_available():
    torch.cuda.empty_cache()
print("Local smoke test complete.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Define the PyFunc wrapper

# COMMAND ----------

import mlflow
import pandas as pd


class SigLIP2EmbeddingModel(mlflow.pyfunc.PythonModel):
    """MLflow PyFunc wrapper for SigLIP 2 SO400M/14-384.

    Input DataFrame columns:
      - input_type: "text" or "image"
      - input_data: text string, or base64-encoded image bytes

    Output DataFrame: single `embedding` column with 1152-float lists.
    """

    def _to_tensor(self, output):
        import torch
        if isinstance(output, torch.Tensor):
            return output
        return output.pooler_output

    def load_context(self, context):
        import torch
        from transformers import AutoModel, AutoProcessor

        model_dir = context.artifacts["model_dir"]
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModel.from_pretrained(model_dir).to(self.device)
        self.model.eval()
        self.processor = AutoProcessor.from_pretrained(model_dir)
        print(f"SigLIP 2 model loaded on {self.device}")

    def _encode_texts(self, texts):
        import torch
        inputs = self.processor(text=texts, return_tensors="pt", padding="max_length").to(self.device)
        with torch.no_grad():
            emb = self._to_tensor(self.model.get_text_features(**inputs))
        emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb.cpu().numpy().tolist()

    def _encode_images(self, base64_strings):
        import base64
        import io
        import torch
        from PIL import Image

        images = []
        for b64 in base64_strings:
            img_bytes = base64.b64decode(b64)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            images.append(img)
        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        with torch.no_grad():
            emb = self._to_tensor(self.model.get_image_features(**inputs))
        emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb.cpu().numpy().tolist()

    def predict(self, context, model_input: pd.DataFrame) -> pd.DataFrame:
        results = [None] * len(model_input)

        text_mask = model_input["input_type"] == "text"
        if text_mask.any():
            text_data = model_input.loc[text_mask, "input_data"].tolist()
            for idx, emb in zip(model_input.index[text_mask], self._encode_texts(text_data)):
                results[idx] = emb

        image_mask = model_input["input_type"] == "image"
        if image_mask.any():
            image_data = model_input.loc[image_mask, "input_data"].tolist()
            for idx, emb in zip(model_input.index[image_mask], self._encode_images(image_data)):
                results[idx] = emb

        return pd.DataFrame({"embedding": results})


print("SigLIP2EmbeddingModel class defined.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log and register the model

# COMMAND ----------

import tempfile
import os
from transformers import AutoModel, AutoProcessor
from mlflow.models import infer_signature

mlflow.set_registry_uri("databricks-uc")

username = spark.sql("SELECT current_user()").collect()[0][0]
mlflow.set_experiment(f"/Users/{username}/siglip2-embedding-experiment")

print(f"Downloading model artifacts for logging...")
siglip_model = AutoModel.from_pretrained(hf_model_id)
siglip_processor = AutoProcessor.from_pretrained(hf_model_id)

tmp_dir = tempfile.mkdtemp()
model_dir = os.path.join(tmp_dir, "siglip2_model")
siglip_model.save_pretrained(model_dir)
siglip_processor.save_pretrained(model_dir)
print(f"Model artifacts saved to {model_dir}")

del siglip_model, siglip_processor

input_example = pd.DataFrame({
    "input_type": ["text"],
    "input_data": ["a photo of a cat"],
})
sample_output = pd.DataFrame({"embedding": [[0.0] * 1152]})
signature = infer_signature(input_example, sample_output)

with mlflow.start_run(run_name="siglip2-so400m-embedding") as run:
    model_info = mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=SigLIP2EmbeddingModel(),
        artifacts={"model_dir": model_dir},
        signature=signature,
        input_example=input_example,
        pip_requirements=[
            "transformers>=4.49.0",
            "torch>=2.0.0",
            "pillow>=10.0.0",
            "sentencepiece",
            "protobuf",
            "numpy",
        ],
        registered_model_name=registered_model_name,
    )
    print(f"Run ID:    {run.info.run_id}")
    print(f"Model URI: {model_info.model_uri}")

from mlflow import MlflowClient
client = MlflowClient(registry_uri="databricks-uc")
versions = client.search_model_versions(f"name='{registered_model_name}'")
latest_version = max(int(v.version) for v in versions)
print(f"Registered: {registered_model_name} v{latest_version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy as a Serving Endpoint
# MAGIC
# MAGIC Idempotent: updates the endpoint config if it already exists. ~30 min for the
# MAGIC GPU instance to provision and the model to load. `scale_to_zero_enabled=False`
# MAGIC keeps it warm for low-latency queries from the app; flip to `True` if cost matters
# MAGIC more than first-query latency.

# COMMAND ----------

import time
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    ServedEntityInput,
    ServingModelWorkloadType,
)
from databricks.sdk.errors import ResourceDoesNotExist

w = WorkspaceClient()

print(f"Deploying endpoint '{endpoint_name}' with {registered_model_name} v{latest_version}...")

served_entity = ServedEntityInput(
    entity_name=registered_model_name,
    entity_version=str(latest_version),
    workload_size="Small",
    workload_type=ServingModelWorkloadType.GPU_SMALL,
    scale_to_zero_enabled=False,
)

try:
    existing = w.serving_endpoints.get(endpoint_name)
    print(f"Endpoint exists. Updating to v{latest_version}...")
    w.serving_endpoints.update_config_and_wait(
        name=endpoint_name,
        served_entities=[served_entity],
    )
except ResourceDoesNotExist:
    print("Creating new endpoint...")
    w.serving_endpoints.create_and_wait(
        name=endpoint_name,
        config=EndpointCoreConfigInput(name=endpoint_name, served_entities=[served_entity]),
    )

print(f"Endpoint '{endpoint_name}' is ready.")
print(f"URL: {w.config.host}/serving-endpoints/{endpoint_name}/invocations")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify the endpoint with a live query

# COMMAND ----------

import base64
import io
import numpy as np
from PIL import Image

print("Test 1: text embeddings")
text_payload = [
    {"input_type": "text", "input_data": "a photo of a cat sitting on a couch"},
    {"input_type": "text", "input_data": "a landscape painting of mountains at sunset"},
]
text_response = w.serving_endpoints.query(name=endpoint_name, dataframe_records=text_payload)
text_predictions = text_response.predictions
for i, pred in enumerate(text_predictions):
    emb = pred["embedding"]
    print(f"  text {i+1}: dim={len(emb)}, first 5={emb[:5]}")

print("\nTest 2: image embedding")
test_img = Image.fromarray(np.random.randint(0, 255, (384, 384, 3), dtype=np.uint8))
buf = io.BytesIO()
test_img.save(buf, format="PNG")
img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
image_response = w.serving_endpoints.query(
    name=endpoint_name,
    dataframe_records=[{"input_type": "image", "input_data": img_b64}],
)
img_emb = image_response.predictions[0]["embedding"]
print(f"  image:  dim={len(img_emb)}, first 5={img_emb[:5]}")

print("\nCosine similarities")
text_emb_1 = np.array(text_predictions[0]["embedding"])
text_emb_2 = np.array(text_predictions[1]["embedding"])
img_emb_arr = np.array(img_emb)
print(f"  text 1 vs image:  {float(np.dot(text_emb_1, img_emb_arr)):.4f}")
print(f"  text 1 vs text 2: {float(np.dot(text_emb_1, text_emb_2)):.4f}")
print("\nEndpoint working.")
