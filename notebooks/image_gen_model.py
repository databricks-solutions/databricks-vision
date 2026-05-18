"""
Custom MLflow pyfunc model that wraps the Responses API with gpt-image-1.5 / gpt-image-2
for batch image generation.

Deployed as a Model Serving endpoint and called via ai_query() for batch inference.
Uses DatabricksOpenAI for automatic auth via injected M2M OAuth credentials.

Per-row tool params (size, quality, image_model, output_format, background) flow
through the predict signature; missing/NaN values fall back to module defaults.
If `background == "transparent"`, model is forced to `gpt-image-1.5` (only model
that supports transparency), mirroring `image_gen.ImageGen._build_tools`.
"""

import base64
import logging
from io import BytesIO

import mlflow
import pandas as pd
from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "low"
DEFAULT_IMAGE_MODEL = "gpt-image-2"
DEFAULT_OUTPUT_FORMAT = "png"
DEFAULT_BACKGROUND = "opaque"
LLM_MODEL = "databricks-gpt-5-5"


def _coerce(value, default: str) -> str:
    """Treat NaN / None / '' as missing; otherwise stringify."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    s = str(value).strip()
    return s or default


class ImageGenerator(mlflow.pyfunc.PythonModel):
    """Generates images using the Responses API (gpt-5.2 + gpt-image-*).

    Input DataFrame columns:
        - input_image_b64 (str): base64-encoded input image
        - reference_image_b64 (str, optional): base64-encoded reference image
        - prompt (str): generation prompt
        - size (str, optional): WxH or 'auto' (default 1024x1024)
        - quality (str, optional): low/medium/high/auto (default low)
        - image_model (str, optional): gpt-image-2 / gpt-image-1.5 (default gpt-image-2)
        - output_format (str, optional): png/jpeg (default png)
        - background (str, optional): opaque/transparent (default opaque);
          when transparent, image_model is forced to gpt-image-1.5

    Output DataFrame columns:
        - output_image_b64 (str): base64-encoded generated image
        - status (str): "success" or "error: <message>"
    """

    def load_context(self, context):
        from databricks_openai import DatabricksOpenAI

        self.client = DatabricksOpenAI()
        logger.info("Model loaded with DatabricksOpenAI auto-auth")

    @staticmethod
    def _compress_b64(image_b64: str, max_side: int = 1024, quality: int = 85) -> str:
        """Resize and compress a base64 image to keep API payloads manageable."""
        raw = base64.b64decode(image_b64)
        img = Image.open(BytesIO(raw))
        if max(img.size) > max_side:
            ratio = max_side / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)))
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()

    def _generate_one(
        self,
        input_b64: str,
        reference_b64: str | None,
        prompt: str,
        size: str,
        quality: str,
        image_model: str,
        output_format: str,
        background: str,
    ) -> dict:
        """Generate a single image via the Responses API."""
        try:
            # Force gpt-image-1.5 for transparency (only model that supports it)
            effective_model = "gpt-image-1.5" if background == "transparent" else image_model

            input_compressed = self._compress_b64(input_b64)

            content = [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_image",
                    "image_url": f"data:image/jpeg;base64,{input_compressed}",
                },
            ]

            if reference_b64:
                ref_compressed = self._compress_b64(reference_b64)
                content.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{ref_compressed}",
                    }
                )

            tool = {
                "type": "image_generation",
                "model": effective_model,
                "quality": quality,
                "size": size,
                "output_format": output_format,
            }
            if background == "transparent":
                tool["background"] = "transparent"

            response = self.client.responses.create(
                model=LLM_MODEL,
                input=[{"role": "user", "content": content}],
                tools=[tool],
                stream=True,
            )

            # Pull the final image bytes from the streamed output_item.done event;
            # stream=True is required to avoid the 655KB non-streamed response cap.
            for event in response:
                if getattr(event, "type", "") == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if item is not None and getattr(item, "type", "") == "image_generation_call":
                        return {"output_image_b64": item.result, "status": "success"}

            return {"output_image_b64": None, "status": "no_image_generated"}

        except Exception as e:
            logger.error("Image generation failed: %s", e)
            return {
                "output_image_b64": None,
                "status": f"error: {e}",
            }

    def predict(self, context, model_input: pd.DataFrame) -> pd.DataFrame:
        results = []
        for _, row in model_input.iterrows():
            ref_b64 = row.get("reference_image_b64")
            if pd.isna(ref_b64) or ref_b64 == "":
                ref_b64 = None

            result = self._generate_one(
                input_b64=row["input_image_b64"],
                reference_b64=ref_b64,
                prompt=row["prompt"],
                size=_coerce(row.get("size"), DEFAULT_SIZE),
                quality=_coerce(row.get("quality"), DEFAULT_QUALITY),
                image_model=_coerce(row.get("image_model"), DEFAULT_IMAGE_MODEL),
                output_format=_coerce(row.get("output_format"), DEFAULT_OUTPUT_FORMAT),
                background=_coerce(row.get("background"), DEFAULT_BACKGROUND),
            )
            results.append(result)
        return pd.DataFrame(results)


mlflow.models.set_model(ImageGenerator())
