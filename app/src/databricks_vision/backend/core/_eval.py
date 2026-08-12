"""MLflow 3 GenAI evaluation for generated images.

The app scores every generated image with multimodal `make_judge` `{{ trace }}` judges
(MLflow 3.15+). The judge can *see* the image because it is captured on an MLflow trace as
an `mlflow-attachment://` reference (via the `get_span_image` tool). We keep the structured
`ImageAnalyzer` call for the enrichment fields a scalar judge can't emit (description, tags,
missing_or_wrong_elements, improved_prompt, criteria_evaluation) and let judges own the
calibratable scores (the 0-5 metrics + safety / brand flags).

Design notes:
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
import json
import re
from io import BytesIO
from typing import TYPE_CHECKING, Any

from PIL import Image as PILImage

from ._config import logger

if TYPE_CHECKING:
    from image_gen import ImageAnalysis, ImageAnalyzer

    from ._config import AppConfig


def metrics_json(analysis: "ImageAnalysis") -> str:
    """Serialize an ImageAnalysis's metrics to the JSON string stored in
    `generated_images.metrics`, nesting per-dimension judge rationales under `_rationales`
    when present (set by ImageEvaluator._merge; absent on the structured-analyzer fallback).

    The gallery reads `metrics._rationales[<metric key>]` to show a hover tooltip per metric
    cell. Use this everywhere the metrics column is written so the shape stays consistent.
    """
    m = analysis.metrics.model_dump()
    m.pop("purpose_fit", None)  # merged into `prompt`; no longer a displayed dimension
    rationales = getattr(analysis, "metric_rationales", None)
    if rationales:
        m["_rationales"] = rationales
    custom = getattr(analysis, "custom_metric", None)
    if custom and custom.get("score") is not None:
        m["_custom"] = custom
    return json.dumps(m)


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

# The fixed set of 5 evaluation criteria shown as the gallery metric grid. Each is a
# {{ trace }} judge (fetches the image via get_span_image); {{ inputs }} carries the prompt.
# These defaults mirror the eval_criteria seed in image_gen._SCHEMA_SQL and are the source of
# truth for reset-to-default + the fallback when the DB table is unavailable.
#
# Criterion key -> the metrics-dict key it fills. `custom` has no fixed metric key; its score
# nests under metrics._custom. `prompt` merges the old prompt-adherence + purpose-fit.
CRITERION_TO_METRIC = {
    "quality": "quality",
    "prompt": "prompt_adherence",
    "text": "text_legibility",
    "safe": "safe_content",
    # "custom" -> metrics._custom (handled specially)
}

DEFAULT_CRITERIA: list[dict[str, Any]] = [
    {"key": "quality", "label": "Quality", "is_custom": False, "instructions": (
        "Evaluate the overall visual and technical quality of the AI-generated image captured "
        "in {{ trace }} (retrieve the image attachment from the trace). Consider composition, "
        "lighting, sharpness, and absence of artifacts. Respond with a single integer 0-5 "
        "(5 = excellent) and a one-sentence rationale.")},
    {"key": "prompt", "label": "Prompt", "is_custom": False, "instructions": (
        "You are evaluating an AI-generated image against the prompt that produced it. The "
        "generation prompt is provided in {{ inputs }}. Inspect the generated image captured in "
        "{{ trace }} (retrieve the image attachment on the generation span). Score how "
        "completely and correctly every element of the prompt is present, AND how well the "
        "image fits the prompt's stated or implied purpose. Respond with a single integer 0-5, "
        "where 5 = every element present, correct, and well-suited to the purpose, and 0 = the "
        "image ignores the prompt. Give a one-sentence rationale.")},
    {"key": "text", "label": "Text", "is_custom": False, "instructions": (
        "Evaluate the clarity and correctness of any text rendered inside the AI-generated "
        "image captured in {{ trace }} (retrieve the image attachment from the trace). The "
        "generation prompt is in {{ inputs }}. Judge whether in-image text is legible and "
        "correctly spelled. If the image contains no text and none was required by the prompt, "
        "give a 5. Respond with a single integer 0-5 (5 = perfectly legible / not applicable) "
        "and a one-sentence rationale.")},
    {"key": "safe", "label": "Safe", "is_custom": False, "instructions": (
        "Inspect the AI-generated image captured in {{ trace }} (retrieve the image attachment "
        "from the trace) for genuine safety issues only: NSFW, graphic content, or harmful "
        "stereotypes. Brand/competitor issues are NOT safety issues. Respond with a single "
        "integer 0-5, where 5 = fully safe and 0 = clearly problematic. In the rationale, name "
        "any specific safety issue found, or state that none were found.")},
    {"key": "custom", "label": "Custom", "is_custom": True, "enabled": False, "instructions": (
        "Evaluate the AI-generated image captured in {{ trace }} (retrieve the image attachment "
        "from the trace) against this custom criterion. The generation prompt is in "
        "{{ inputs }}. Describe here what you want scored (edit this in Settings). Respond with "
        "a single integer 0-5 (5 = fully meets the criterion) and a one-sentence rationale.")},
]

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


def load_criteria(pool) -> list[dict[str, Any]]:
    """Load the 5 eval criteria from the eval_criteria table (ordered), falling back to
    DEFAULT_CRITERIA if the pool/table is unavailable. Each row: key, label, instructions,
    is_custom, enabled."""
    if pool is None:
        return [{**c, "enabled": c.get("enabled", True)} for c in DEFAULT_CRITERIA]
    try:
        from psycopg.rows import dict_row
        with pool.connection() as conn:
            # The app pool defaults to dict_row; force it here so access is by column name
            # regardless of the pool's configured row factory.
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT key, label, instructions, is_custom, enabled FROM eval_criteria "
                    "ORDER BY sort_order, key"
                )
                rows = cur.fetchall()
            conn.commit()
        if not rows:
            return [{**c, "enabled": c.get("enabled", True)} for c in DEFAULT_CRITERIA]
        return [
            {"key": r["key"], "label": r["label"], "instructions": r["instructions"],
             "is_custom": r["is_custom"], "enabled": r["enabled"]}
            for r in rows
        ]
    except Exception as exc:
        logger.warning("load_criteria failed (%s); using DEFAULT_CRITERIA", exc)
        return [{**c, "enabled": c.get("enabled", True)} for c in DEFAULT_CRITERIA]


# Our image judges MUST reference the generated image via {{ trace }} — that placeholder is
# what lets the judge call get_span_image to fetch the attachment. make_judge itself only
# requires *some* template variable, so a trace-less instruction would build yet score images
# blind; we therefore require {{ trace }} explicitly. Accepts {{trace}} and {{ trace }}.
_TRACE_VAR_RE = re.compile(r"\{\{\s*trace\s*\}\}")


def _make_judge(name: str, instructions: str, value_type: Any, model: str, reasoning_effort: str | None):
    """Construct a single MLflow judge with the app's standard inference params."""
    from mlflow.genai.judges import make_judge

    inference_params = (
        {"reasoning_effort": reasoning_effort}
        if reasoning_effort and reasoning_effort.lower() != "default"
        else None
    )
    return make_judge(
        name=name,
        instructions=instructions,
        model=model,
        feedback_value_type=value_type,
        inference_params=inference_params,
    )


def validate_criterion_instructions(instructions: str | None, model: str, reasoning_effort: str | None) -> None:
    """Validate a criterion's instructions BEFORE they are persisted. Raises ValueError with a
    user-facing message if they can't produce a working image judge. Used by the eval-criteria
    PATCH endpoint so invalid instructions are rejected at the door instead of silently killing
    scoring (and disabling eval entirely on the next restart)."""
    if instructions is None or not instructions.strip():
        raise ValueError("Instructions cannot be empty.")
    if not _TRACE_VAR_RE.search(instructions):
        raise ValueError(
            "Instructions must include the {{ trace }} placeholder so the judge can see the "
            "generated image. Keep {{ trace }} in the text."
        )
    # Trial build to surface any other make_judge rejection before it reaches the DB.
    try:
        _make_judge("_validate", instructions, int, model, reasoning_effort)
    except Exception as exc:
        raise ValueError(f"Invalid judge instructions: {str(exc).splitlines()[0]}") from exc


def build_judges(model: str, reasoning_effort: str | None, criteria: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one MLflow {{ trace }} int-0-5 judge per enabled criterion (keyed by criterion
    key), plus the conditional brand_conflict / criteria_adherence judges (invoked only when
    the caller supplies style criteria — separate from the 5-cell grid).

    Rebuilt whenever criteria change (see ImageEvaluator.refresh_criteria). Per-criterion
    construction is guarded: a single bad criterion (e.g. one hand-edited into the DB without
    going through the validating PATCH endpoint) drops only its own judge instead of taking
    down the whole set or bricking startup.
    """
    judges: dict[str, Any] = {}
    for c in criteria:
        if not c.get("enabled", True):
            continue
        try:
            judges[c["key"]] = _make_judge(c["key"], c["instructions"], int, model, reasoning_effort)
        except Exception as exc:
            logger.warning("Skipping eval criterion %r — invalid judge instructions: %s",
                           c.get("key"), str(exc).splitlines()[0])
    # Conditional judges (criteria-driven, not part of the grid).
    judges["brand_conflict"] = _make_judge("brand_conflict", _BRAND_CONFLICT_INSTRUCTIONS, str, model, reasoning_effort)
    judges["criteria_adherence"] = _make_judge("criteria_adherence", _CRITERIA_ADHERENCE_INSTRUCTIONS, int, model, reasoning_effort)
    return judges


# --- Evaluator --------------------------------------------------------------


class ImageEvaluator:
    """Runs the traced structured analysis + judge scoring for one image, and merges the
    result into the shape the gallery expects (an ImageAnalysis-compatible dict).

    Non-fatal by contract: any failure falls back to the plain structured analysis so the
    image still lands in the gallery (matching the app's existing best-effort behavior).
    """

    def __init__(self, cfg: "AppConfig", pool=None):
        self._cfg = cfg
        self._max_px = cfg.eval_image_max_px
        self._pool = pool
        self._criteria: list[dict[str, Any]] = []
        self._criteria_sig: str = ""
        self._judges: dict[str, Any] = {}
        self.refresh_criteria(pool)

    @staticmethod
    def _sig(criteria: list[dict[str, Any]]) -> str:
        """Cheap signature of the criteria set to detect changes (label/instructions/enabled)."""
        return json.dumps(
            [(c["key"], c.get("label"), c.get("instructions"), c.get("enabled", True)) for c in criteria],
            sort_keys=True,
        )

    def refresh_criteria(self, pool) -> None:
        """(Re)load criteria from the DB and rebuild the judge set. Called at startup, after a
        Settings edit, and lazily per score_image (so all uvicorn workers self-heal).

        Build-then-commit: the new criteria/signature/judges are only assigned after
        build_judges succeeds, so a failed rebuild leaves the last-good set untouched rather
        than half-updating state. (build_judges is itself per-criterion guarded, so this only
        raises for a hard failure like the model/params being unusable.)"""
        if pool is not None:
            self._pool = pool
        criteria = load_criteria(self._pool)
        judges = build_judges(
            self._cfg.judge_model, self._cfg.judge_reasoning_effort, criteria,
        )
        self._criteria = criteria
        self._criteria_sig = self._sig(criteria)
        self._judges = judges

    def _reload_if_changed(self) -> None:
        """Reload criteria from the DB and rebuild judges only if they changed. Runs at the
        start of each (background) scoring so edits made on any worker take effect everywhere,
        without a per-image judge rebuild when nothing changed. Any failure leaves the
        last-good judge set in place (best-effort)."""
        try:
            latest = load_criteria(self._pool)
            if self._sig(latest) != self._criteria_sig:
                judges = build_judges(
                    self._cfg.judge_model, self._cfg.judge_reasoning_effort, latest,
                )
                self._criteria = latest
                self._criteria_sig = self._sig(latest)
                self._judges = judges
        except Exception as exc:
            logger.warning("criteria reload failed; keeping last-good judges: %s", exc)

    @property
    def _custom_criterion(self) -> dict[str, Any] | None:
        for c in self._criteria:
            if c.get("is_custom") and c.get("enabled", True):
                return c
        return None

    def _downscale(self, image_bytes: bytes) -> bytes:
        """Downscale to a JPEG bounded by max_px on the long edge — keeps the trace attachment
        under MLflow's ~10MB cap and cuts each judge's fetch cost. Full-res stays in the Volume."""
        img = PILImage.open(BytesIO(image_bytes))
        img.thumbnail((self._max_px, self._max_px), PILImage.LANCZOS)
        # Transparent-background images (gpt-image-1.5) are RGBA/LA/P-with-transparency. A plain
        # convert("RGB") drops alpha and renders transparent pixels as black, so the judges would
        # score the image against a black background. Composite onto white first to preserve intent.
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            bg = PILImage.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
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

        # Pick up any Settings edits (possibly made on another uvicorn worker) before scoring.
        await asyncio.to_thread(self._reload_if_changed)

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

        # The 5-cell grid judges are the enabled criterion keys. brand_conflict /
        # criteria_adherence run only when the caller supplied style criteria.
        # Only run keys that actually have a built judge: build_judges drops a criterion whose
        # make_judge failed (per-criterion isolation), so indexing self._judges by every enabled
        # key would KeyError and sink ALL scoring — defeating that isolation.
        active = [c["key"] for c in self._criteria
                  if c.get("enabled", True) and c["key"] in self._judges]
        if criteria:
            active += [n for n in ("brand_conflict", "criteria_adherence") if n in self._judges]

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

        merged = self._merge(analysis, feedbacks)

        # Rule: anything with issues gets an improved prompt. The structured analyzer only
        # returns a rewrite for images it deems clearly off-spec, so a middling image (a weak
        # judge score but no analyzer rewrite) would otherwise show none. When judges flag a
        # weak dimension and there's no rewrite yet, generate a real one grounded in the weak
        # dimensions + their rationales. Non-fatal: on any failure we just leave it unset.
        weak = self._weak_dimensions(merged)
        if weak and not merged.improved_prompt:
            try:
                merged.improved_prompt = await self._generate_improved_prompt(
                    analyzer, prompt, weak, criteria,
                )
            except Exception as exc:
                logger.warning("improved-prompt generation failed: %s", exc)

        return merged

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
        """Overwrite the scoring fields on `analysis` with judge values (keyed by CRITERION key),
        keeping the enrichment fields from the structured call. Mutates and returns `analysis`.

        The four built-in criteria fill their mapped metric keys (see CRITERION_TO_METRIC); the
        `custom` criterion has no fixed metric field, so its score/label/rationale nest under
        `metrics._custom`. Per-dimension rationales are stashed on `analysis.metric_rationales`
        (keyed by metric-dict key) for the hover tooltips. See `metrics_json`.
        """
        rationales: dict[str, str] = {}

        # Built-in criteria -> their metric-dict keys.
        for crit_key, metric_key in CRITERION_TO_METRIC.items():
            fb = feedbacks.get(crit_key)
            if fb is None:
                continue
            s = self._score(fb)
            if s is not None:
                setattr(analysis.metrics, metric_key, s)
            rat = getattr(fb, "rationale", None)
            if rat:
                rationales[metric_key] = rat
                if crit_key == "prompt":
                    analysis.evaluation = rat  # judge's grounded critique
                if crit_key == "safe" and s is not None and s <= 2 and not analysis.safety_flags:
                    analysis.safety_flags = [rat]

        # Custom criterion -> metrics._custom (label + score + rationale).
        custom = self._custom_criterion
        custom_payload = None
        if custom is not None:
            fb = feedbacks.get("custom")
            if fb is not None:
                s = self._score(fb)
                custom_payload = {
                    "label": custom.get("label", "Custom"),
                    "score": s,
                    "rationale": getattr(fb, "rationale", None),
                }
        # Stash the rationales + custom payload without touching the shared Pydantic schema.
        object.__setattr__(analysis, "metric_rationales", rationales)
        object.__setattr__(analysis, "custom_metric", custom_payload)

        brand = feedbacks.get("brand_conflict")
        if brand is not None and str(getattr(brand, "value", "")).lower().startswith("conflict"):
            if getattr(brand, "rationale", None) and not analysis.brand_conflicts:
                analysis.brand_conflicts = [brand.rationale]

        crit = feedbacks.get("criteria_adherence")
        if crit is not None and getattr(crit, "rationale", None) and not analysis.criteria_evaluation:
            analysis.criteria_evaluation = crit.rationale

        return analysis

    # A metric below this (matches the gallery's green threshold) counts as a weak dimension
    # worth an improved-prompt suggestion.
    _WEAK_THRESHOLD = 4

    def _weak_dimensions(self, analysis: "ImageAnalysis") -> list[tuple[str, int, str]]:
        """Return [(label, score, rationale)] for dimensions scoring below threshold (the four
        built-in metrics + the custom one), driving improved-prompt generation."""
        labels = {
            "quality": "visual quality", "prompt_adherence": "prompt adherence",
            "text_legibility": "text legibility", "safe_content": "safe content",
        }
        rationales = getattr(analysis, "metric_rationales", {}) or {}
        m = analysis.metrics.model_dump()
        out = []
        for key, label in labels.items():
            score = m.get(key)
            if isinstance(score, int) and score < self._WEAK_THRESHOLD:
                out.append((label, score, rationales.get(key, "")))
        custom = getattr(analysis, "custom_metric", None)
        if custom and isinstance(custom.get("score"), int) and custom["score"] < self._WEAK_THRESHOLD:
            out.append((custom.get("label", "custom").lower(), custom["score"], custom.get("rationale") or ""))
        return out

    async def _generate_improved_prompt(
        self, analyzer: "ImageAnalyzer", prompt: str,
        weak: list[tuple[str, int, str]], criteria: str | None,
    ) -> str | None:
        """Generate a concrete rewritten generation prompt that addresses the weak dimensions.
        Uses the analyzer's own OpenAI client/model (a plain text completion — no image needed;
        the weak-dimension rationales already describe what to fix)."""
        weak_lines = "\n".join(f"- {label} scored {score}/5: {rat}" for label, score, rat in weak)
        crit_line = f"\nEvaluation criteria to honor:\n{criteria}\n" if criteria else ""
        instruction = (
            "You rewrite text-to-image generation prompts to fix specific weaknesses.\n"
            f"Original prompt:\n{prompt}\n{crit_line}\n"
            f"An evaluator scored the generated image and flagged these weak areas:\n{weak_lines}\n\n"
            "Rewrite the original prompt so a new generation would score better on those areas. "
            "Keep the original intent and subject; add only concrete, visual specifics that "
            "address the weaknesses. Return ONLY the rewritten prompt text, nothing else."
        )
        resp = await analyzer.client.responses.create(model=analyzer.model, input=instruction)
        text = (resp.output_text or "").strip()
        return text or None
