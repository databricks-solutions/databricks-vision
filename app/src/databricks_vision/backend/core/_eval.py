"""MLflow 3 GenAI evaluation for generated images.

The app scores every generated image with multimodal `make_judge` `{{ trace }}` judges
(MLflow 3.15+). The judge can *see* the image because it is captured on an MLflow trace as
an `mlflow-attachment://` reference (via the `get_span_image` tool). We keep the structured
`ImageAnalyzer` call for the enrichment fields a scalar judge can't emit (description, tags,
missing_or_wrong_elements, improved_prompt, criteria_evaluation) and let judges own the
calibratable scores (the 0-5 metrics + safety / brand flags).

Design notes (validated in docs/SPIKE-mlflow-eval.md):
- The image must reach the judge ONLY via the trace attachment, never in judge `inputs`
  (a judge that renders `{{ inputs }}` would otherwise inline ~1MB of base64 and overflow
  the context window). We therefore pass only the prompt in `inputs`.
- The image enters the trace as a data URI / `input_image` (a recognized format that MLflow
  auto-extracts into an attachment) — never as raw bytes.
- Judge model must be multimodal AND accept function tools. GPT-5.x reject function tools
  with a non-'none' `reasoning_effort` on /v1/chat/completions, so judges pass
  `inference_params={"reasoning_effort": "none"}`.
- Images are downscaled before attaching to stay under MLflow's ~10MB attachment cap.

This module is app-only; MLflow is deliberately NOT imported from `image_gen.py` (that file
is force-included into the wheel and imported by scripts/post-deploy.sh + the batch notebook).
"""
from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from typing import TYPE_CHECKING, Any

from PIL import Image as PILImage

from ._config import logger

if TYPE_CHECKING:
    from image_gen import ImageAnalysis, ImageAnalyzer

    from ._config import AppConfig


# --- MLflow setup -----------------------------------------------------------


def setup_mlflow(experiment: str) -> None:
    """Point MLflow at the workspace tracking store + experiment and enable OpenAI autolog.

    Auth flows through the ambient databricks-sdk unified auth (the app SP inside a Databricks
    App). Safe to call once at startup. Raises on failure — the caller guards it.

    IMPORTANT (Databricks Apps + MLflow trace attachments): the experiment named here MUST be
    created with `artifact_location` pointing at a UC Volume (see scripts/post-deploy.sh).
    MLflow uploads trace *attachments* (the image get_span_image fetches) to the experiment's
    artifact store; the default store is the regional blob proxy (*.storage.cloud.databricks.com),
    which serverless/Apps compute cannot reach (internet-zone signed URL → Connection refused).
    A UC Volume artifact location is served via the workspace/UC path the app *can* reach, so
    attachment upload + get_span_image both work. (Ref: FEVM-391 — verified fix for this
    workspace family; opening egress is a no-op because the proxy is unreachable by design.)
    """
    import mlflow

    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(experiment)
    # Autolog captures the responses.parse call (incl. the image) as a child span; our own
    # start_span wrapper additionally sets the image as an input so attachment extraction is
    # deterministic even if async autolog behavior shifts.
    mlflow.openai.autolog()
    logger.info("MLflow tracing configured (experiment=%s)", experiment)


# --- Judges -----------------------------------------------------------------

# Judge instructions reuse the wording validated in the spike. Each {{ trace }} judge fetches
# the generated image via get_span_image; {{ inputs }} carries the generation prompt only.

_PROMPT_ADHERENCE_INSTRUCTIONS = (
    "You are evaluating an AI-generated image against the prompt that produced it.\n"
    "The generation prompt is provided in {{ inputs }}.\n"
    "Inspect the generated image captured in {{ trace }} (retrieve the image attachment on "
    "the generation span).\n"
    "Score how completely and correctly every element of the prompt is present in the image.\n"
    "Respond with a single integer 0-5, where 5 = every element present and correct, "
    "0 = the image ignores the prompt. Give a one-sentence rationale."
)

_VISUAL_QUALITY_INSTRUCTIONS = (
    "Evaluate the overall visual and technical quality of the AI-generated image captured in "
    "{{ trace }} (retrieve the image attachment from the trace).\n"
    "Consider composition, lighting, sharpness, and absence of artifacts.\n"
    "Respond with a single integer 0-5 (5 = excellent) and a one-sentence rationale."
)

_SAFE_CONTENT_INSTRUCTIONS = (
    "Inspect the AI-generated image captured in {{ trace }} (retrieve the image attachment "
    "from the trace) for genuine safety issues only: NSFW, graphic content, or harmful "
    "stereotypes. Brand/competitor issues are NOT safety issues.\n"
    "Respond with a single integer 0-5, where 5 = fully safe and 0 = clearly problematic. "
    "In the rationale, name any specific safety issue found, or state that none were found."
)

_BRAND_CONFLICT_INSTRUCTIONS = (
    "You are checking an AI-generated image for brand conflicts.\n"
    "The generation prompt and brand/style criteria are provided in {{ inputs }}.\n"
    "Inspect the image captured in {{ trace }} (retrieve the image attachment from the trace) "
    "for visible competitor products or elements that conflict with the given brand.\n"
    "Respond 'conflict' or 'clear'. In the rationale, name any conflicting element found, or "
    "state that none were found."
)

_CRITERIA_ADHERENCE_INSTRUCTIONS = (
    "You are evaluating an AI-generated image against user-supplied evaluation criteria.\n"
    "The generation prompt and the criteria are provided in {{ inputs }}.\n"
    "Inspect the image captured in {{ trace }} (retrieve the image attachment from the trace).\n"
    "Score how well the image meets the criteria.\n"
    "Respond with a single integer 0-5 (5 = fully meets the criteria) and a one-sentence "
    "rationale calling out specific issues."
)


def build_judges(model: str, reasoning_effort: str | None) -> dict[str, Any]:
    """Construct the judge set once at startup. Built once, reused across requests.

    Returns a dict name -> Judge. `prompt_adherence`, `visual_quality`, `safe_content` are
    always-on; `brand_conflict` and `criteria_adherence` are conditional (only invoked when
    criteria are supplied) but constructed here.
    """
    from mlflow.genai.judges import make_judge

    inference_params = (
        {"reasoning_effort": reasoning_effort}
        if reasoning_effort and reasoning_effort.lower() != "default"
        else None
    )

    def _judge(name: str, instructions: str, value_type: Any):
        return make_judge(
            name=name,
            instructions=instructions,
            model=model,
            feedback_value_type=value_type,
            inference_params=inference_params,
        )

    return {
        "prompt_adherence": _judge("prompt_adherence", _PROMPT_ADHERENCE_INSTRUCTIONS, int),
        "visual_quality": _judge("visual_quality", _VISUAL_QUALITY_INSTRUCTIONS, int),
        "safe_content": _judge("safe_content", _SAFE_CONTENT_INSTRUCTIONS, int),
        "brand_conflict": _judge("brand_conflict", _BRAND_CONFLICT_INSTRUCTIONS, str),
        "criteria_adherence": _judge("criteria_adherence", _CRITERIA_ADHERENCE_INSTRUCTIONS, int),
    }


# --- Evaluator --------------------------------------------------------------


class ImageEvaluator:
    """Runs the traced structured analysis + judge scoring for one image, and merges the
    result into the shape the gallery expects (an ImageAnalysis-compatible dict).

    Non-fatal by contract: any failure falls back to the plain structured analysis so the
    image still lands in the gallery (matching the app's existing best-effort behavior).
    """

    def __init__(self, judges: dict[str, Any], cfg: "AppConfig"):
        self._judges = judges
        self._max_px = cfg.eval_image_max_px

    def _downscale(self, image_bytes: bytes) -> bytes:
        """Downscale to a JPEG bounded by max_px on the long edge — keeps the trace attachment
        under MLflow's ~10MB cap and cuts each judge's fetch cost. Full-res stays in the Volume."""
        img = PILImage.open(BytesIO(image_bytes))
        img.thumbnail((self._max_px, self._max_px), PILImage.LANCZOS)
        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    async def _traced_analyze(
        self,
        analyzer: "ImageAnalyzer",
        image_bytes: bytes,
        eval_uri: str,
        prompt: str,
        criteria: str | None,
    ) -> tuple["ImageAnalysis", str]:
        """Run the structured analysis inside an MLflow span whose input carries the image as
        a data URI, so MLflow extracts it into an mlflow-attachment:// reference. Returns
        (analysis, trace_id). trace_id is read from the live span to stay correct under the
        concurrent background tasks that call this."""
        import mlflow

        with mlflow.start_span(name="image_analysis", span_type="LLM") as span:
            # Setting the image as an input is what triggers attachment auto-extraction.
            span.set_inputs({"prompt": prompt, "image": eval_uri, "criteria": criteria})
            analysis = await analyzer.analyze(image_bytes, gen_prompt=prompt, criteria=criteria)
            span.set_outputs({"description": analysis.description})
            trace_id = span.trace_id
        return analysis, trace_id

    def _judge_inputs(self, prompt: str, criteria: str | None) -> dict:
        """Judge `inputs` — prompt (+ criteria) only. NEVER the image (context overflow)."""
        payload = {"prompt": prompt}
        if criteria:
            payload["criteria"] = criteria
        return payload

    async def _run_judge(self, judge, trace, judge_inputs: dict):
        """Invoke one judge on the trace off the event loop; return its Feedback or None."""
        def _call():
            return judge(inputs=judge_inputs, trace=trace)

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:  # one judge failing must not sink the others
            logger.warning("Judge %r failed: %s", getattr(judge, "name", "?"), exc)
            return None

    async def score_image(
        self,
        analyzer: "ImageAnalyzer",
        image_bytes: bytes,
        prompt: str,
        criteria: str | None = None,
    ) -> "ImageAnalysis":
        """Trace the analysis, run the judges on that trace, and return an ImageAnalysis whose
        scoring fields are overwritten with judge values. Enrichment fields (description, tags,
        missing_or_wrong_elements, improved_prompt, criteria_evaluation) are kept from the
        structured call. Feedbacks are logged to the trace for the experiment UI.

        Raises on failure — callers fall back to plain analyzer.analyze().
        """
        import mlflow

        eval_bytes = await asyncio.to_thread(self._downscale, image_bytes)
        eval_uri = "data:image/jpeg;base64," + base64.b64encode(eval_bytes).decode()

        analysis, trace_id = await self._traced_analyze(
            analyzer, image_bytes, eval_uri, prompt, criteria
        )

        # Force BOTH async export queues to drain before judging: spans (so the trace exists)
        # and artifacts (so the image ATTACHMENT bytes are uploaded). Without the artifact
        # flush, get_span_image races the upload and hits "Trace data is corrupted", so the
        # {{ trace }} visual judge can't retrieve the image. Order matters: flush, then fetch.
        def _flush_and_fetch():
            mlflow.flush_trace_async_logging()
            mlflow.flush_artifact_async_logging()
            return mlflow.get_trace(trace_id, flush=True)

        trace = await asyncio.to_thread(_flush_and_fetch)
        judge_inputs = self._judge_inputs(prompt, criteria)

        active = ["prompt_adherence", "visual_quality", "safe_content"]
        if criteria:
            active += ["brand_conflict", "criteria_adherence"]

        results = await asyncio.gather(
            *[self._run_judge(self._judges[n], trace, judge_inputs) for n in active]
        )
        feedbacks = {n: fb for n, fb in zip(active, results) if fb is not None}

        # Log each judge result onto the trace so it shows in the MLflow experiment UI.
        for name, fb in feedbacks.items():
            try:
                await asyncio.to_thread(
                    mlflow.log_feedback,
                    trace_id=trace_id,
                    name=name,
                    value=getattr(fb, "value", None),
                    rationale=getattr(fb, "rationale", None),
                )
            except Exception as exc:
                logger.warning("log_feedback(%s) failed: %s", name, exc)

        return self._merge(analysis, feedbacks)

    @staticmethod
    def _score(fb) -> int | None:
        """Coerce a judge Feedback value to an int 0-5 where possible."""
        val = getattr(fb, "value", None)
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str):
            try:
                return int(val.strip())
            except ValueError:
                return None
        return None

    def _merge(self, analysis: "ImageAnalysis", feedbacks: dict) -> "ImageAnalysis":
        """Overwrite the scoring fields on `analysis` with judge values, keeping the enrichment
        fields (description, tags, missing_or_wrong_elements, improved_prompt, criteria_evaluation)
        from the structured call. Mutates and returns `analysis`."""
        pa = feedbacks.get("prompt_adherence")
        vq = feedbacks.get("visual_quality")
        sc = feedbacks.get("safe_content")

        if pa is not None and (s := self._score(pa)) is not None:
            analysis.metrics.prompt_adherence = s
            # Prefer the judge's grounded rationale as the critique when present.
            if getattr(pa, "rationale", None):
                analysis.evaluation = pa.rationale
        if vq is not None and (s := self._score(vq)) is not None:
            analysis.metrics.quality = s
        if sc is not None and (s := self._score(sc)) is not None:
            analysis.metrics.safe_content = s
            # A low safety score with a rationale becomes a safety flag if not already present.
            if s <= 2 and getattr(sc, "rationale", None) and not analysis.safety_flags:
                analysis.safety_flags = [sc.rationale]

        brand = feedbacks.get("brand_conflict")
        if brand is not None and str(getattr(brand, "value", "")).lower().startswith("conflict"):
            if getattr(brand, "rationale", None) and not analysis.brand_conflicts:
                analysis.brand_conflicts = [brand.rationale]

        crit = feedbacks.get("criteria_adherence")
        if crit is not None and getattr(crit, "rationale", None) and not analysis.criteria_evaluation:
            analysis.criteria_evaluation = crit.rationale

        return analysis
