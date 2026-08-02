# Spike: Pivot the databricks-vision eval features onto MLflow 3 GenAI

**Status:** PoC validated ✅ (Phase 1 done) / not yet integrated · **Date:** 2026-07-31 ·
**Trigger:** MLflow 3.15.0 ships multimodal attachments in LLM judges — `{{ trace }}` judges
created with `make_judge()` can now *see* images captured in trace spans.

This is a spike, not a design sign-off. It answers: *is it worth pivoting our home-grown
image evaluation onto MLflow, and what would that actually look like?* No production code
changed.

## Production outcome (2026-08-02): deployed + working in the app ✅

The integration is **live in the `databricks-vision` app** and multimodal judges score real
generations end-to-end. On the deployed app, a generation produces MLflow traces in
`/Shared/databricks-vision-eval` with all judges scoring — including `visual_quality`, whose
rationales describe the actual image ("Excellent composition with warm natural lighting, strong
focus and texture"), proving `get_span_image` fetches the image in the App runtime. Scores
mirror back into the `generated_images` gallery columns.

**The one hard problem and its fix (Databricks Apps egress).** In the App runtime, MLflow's
default trace **artifact** store is the regional blob proxy (`*.storage.cloud.databricks.com`),
which serverless/Apps compute **cannot reach** (internet-zone signed URL → `Connection refused`).
So attachment upload failed and `get_span_image` couldn't fetch the image. Researching internal
history found this is a known FEVM issue (JIRA **FEVM-391** + the FE Slack thread), closed
"not a defect": **opening egress is a no-op — the proxy is unreachable by design.** The verified
fix, entirely within workspace-admin scope, is to create the MLflow experiment with
**`artifact_location` on a UC Volume** (a path the app already reaches) and grant the app SP
`READ VOLUME`/`WRITE VOLUME` + `CAN_EDIT` on the experiment. `scripts/post-deploy.sh` now does
this automatically.

Two gotchas worth recording:
- **Wheel caching:** the app wheel version is derived from the git hash, so *uncommitted* edits
  produce an identically-named wheel and the Apps runtime logs "Requirements have not changed.
  Skipping installation" — your new code never installs. **Commit to force a reinstall.**
- **Contaminated experiments:** an experiment that was ever bound via
  `set_experiment(trace_location=UnityCatalog(...))` is *permanently* stamped with a UC-table
  trace destination that routes attachments back to the blob proxy. Use a **fresh** experiment
  whose only trace config is the Volume `artifact_location`.

---

## PoC outcome (2026-07-31): validated end-to-end (notebook) ✅

`notebooks/03_MLFLOW_EVAL_POC.py` ran clean over 5 corpus images in the workspace. All three
`{{ trace }}` judges (`prompt_adherence`, `visual_quality`, `safe_content`) scored every image
on `databricks-gpt-5-5`, and — the decisive evidence — **the rationales reference actual visual
content** the judge could only know by seeing the image (e.g. "low-key lighting, sharp eyes and
fur detail" on the panther; "golden-hour … minor AI/smoothing artifacts in the mane"; "natural
caustics" underwater). The image renders in the trace UI as an `image_uri` attachment, and §4b's
`mlflow-attachment://` check passed. So `get_span_image` genuinely fed images to the judge:
the 3.15.0 multimodal-judge path **works in this workspace**. Every infra + mechanic risk from
the original spike is now cleared; remaining work is integration design (Phase 2+), not
feasibility.

---

## Live pre-flight (verified 2026-07-31, `databricks-vision` workspace)

The three things the PoC depends on were checked live via CLI/SDK before running the notebook:

- ✅ **Judge model is multimodal and healthy.** `databricks-gpt-5-5` is served in-workspace
  (Foundation Model route; description confirms multimodal text+image, 400K context). A live
  Responses-API call with an `input_image` correctly identified a synthetic red square as
  "Red" — the judge path works here. (`databricks-gpt-5-6-sol` / `-luna` are also available
  as multimodal alternates.)
- ✅ **Corpus has data to evaluate.** Lakebase `generated_images` holds **66** usable rows
  (success + volume_path + prompt), all 66 with prior `ImageAnalyzer` `metrics` — a ready-made
  baseline for judge comparison. Postgres host `ep-sweet-violet-d2bbgdez.database.us-east-1…`.
- ✅ **Images are readable** from the UC Volumes under
  `/Volumes/vision_image_gen_catalog/image_generation/vision_images/…`.

Net: the only remaining unknown is the MLflow-specific mechanic itself (does 3.15.0's
`get_span_image` actually surface the attached image to the judge), which is what the notebook
exercises. The infra risks are cleared.

### PoC run result (2026-07-31): mechanic works; judge model must be Claude

First run of the notebook **confirmed the core mechanic**: the generated image is captured on
the trace span (visible as `image_bytes` in the span inputs) and the traced multimodal call
accurately described the actual image (an emperor penguin bowing to its chick). Trace capture +
multimodal understanding both work live.

However, **all three judges errored** with:

> `Function tools with reasoning_effort not supported for gpt-5.5 in /v1/chat/completions.
> To use function tools, use /v1/responses or set reasoning_effort to 'none'.`

Root cause + fix (verified live):
- A `{{ trace }}` judge fetches the image via a **`get_span_image` function tool**. MLflow
  invokes the judge model over `/v1/chat/completions`, and by default a `reasoning_effort` is
  set.
- **GPT-5.x reject function tools + a non-`'none'` `reasoning_effort` on chat/completions.**
  This is a *parameter* constraint, not a capability gap — GPT-5.5 is fully multimodal (it's
  fine for the §4 *describe* call via `/v1/responses`, and it read a test image correctly).
- **Fix: pass `inference_params={"reasoning_effort": "none"}` to `make_judge`.** With that,
  `databricks-gpt-5-5` handles image + function tool correctly (smoke-tested: returned the
  right color). `make_judge` exposes exactly this via its `inference_params` argument.
  - Verified matrix: gpt-5-5 + tool, *no* effort → ❌ (model applies a default effort);
    gpt-5-5 + tool, effort `'none'` → ✅; gpt-5-mini + tool, effort `'none'` → ❌ (mini rejects
    `'none'`); claude-sonnet-4-5 + tool → ✅ (no knob needed); gemini-2-5-pro → deprecated here.
- **Decision: keep judges on `databricks-gpt-5-5`** with `reasoning_effort='none'`, so the
  eval path stays on the same model family as generation/analysis. Claude
  (`databricks-claude-sonnet-4-5`) is a drop-in alternative that needs no param, if we later
  want to decouple providers. The notebook default is gpt-5-5 + a `judge_reasoning_effort`
  widget.

## TL;DR

- **The 3.15.0 claim checks out**, with one crucial mechanic to internalise: judges don't
  receive the image because it's in the prompt — they call a **`get_span_image` tool** that
  pulls **attachments off a trace span** and passes them to a multimodal model
  (Anthropic / Gemini / OpenAI-compatible via litellm). So the entire pivot hinges on us
  **producing MLflow traces with image attachments**, which we don't do today.
- Our current evaluator (`ImageAnalyzer`) is a **single structured Responses-API call** that
  returns a rich Pydantic object (`description`, `tags`, `evaluation`, five 0–5 `metrics`,
  issue lists, `improved_prompt`, `criteria_evaluation`). It doubles as our **metadata
  enrichment** pipeline (tags + description feed FTS and badges), not just scoring.
- MLflow judges are a **natural fit for the scoring half** and bring real wins: an
  experiment UI, historical runs, per-dimension aggregate metrics, regression comparison,
  SME labeling + judge alignment (MemAlign), and prompt optimization (GEPA). The
  metadata-enrichment half (tags/description feeding search) should **stay** as a direct
  model call.
- **Recommended shape:** keep the inline per-image enrichment call for product UX, and add
  MLflow as a **parallel offline/opt-in evaluation layer** — trace generations, log the
  image as a span attachment, and run `make_judge()` scorers over those traces. Do **not**
  rip out `ImageAnalyzer` and put a serving round-trip on the hot path.
- **Biggest risks:** hot-path latency, judge model availability (our workspace's image path
  is currently 502-ing on the backend — see the recent outage; judges need a *working*
  multimodal endpoint), and MLflow version floor (3.15.0 for multimodal judges, 3.9.0 for UC
  trace ingestion). MLflow is not currently a dependency of this repo at all.

---

## 1. What we have today

All eval logic lives in `image_gen.py` and is invoked from the app's background task after a
generation is persisted.

### The evaluator: `ImageAnalyzer` (`image_gen.py:1315`)

One call — `client.responses.parse(model="databricks-gpt-5-5", …, text_format=ImageAnalysis)`
— sends the image (base64 data URI) + optional generation prompt + optional criteria, and
returns a structured `ImageAnalysis` (`image_gen.py:270`):

| Field | Type | Purpose |
|---|---|---|
| `description` | str | 1–2 sentence factual description — **feeds FTS + gallery** |
| `tags` | list[str] | 5–10 keywords — **feeds FTS + badges** |
| `evaluation` | str | critique paragraph |
| `metrics` | 5×int 0–5 | quality, prompt_adherence, purpose_fit, text_legibility, safe_content |
| `missing_or_wrong_elements` | list[str] | prompt elements absent/incorrect |
| `safety_flags` | list[str] | NSFW / graphic / harmful-stereotype |
| `brand_conflicts` | list[str] | competitor products vs supplied brand |
| `improved_prompt` | str? | rewrite suggestion for off-spec images |
| `criteria_evaluation` | str? | assessment vs user-supplied style guidelines |

### Where it runs

- **Single/edit:** `app/.../routers/generate.py:_save_and_analyze` — writes the gallery row
  immediately (Phase 1), then runs `analyzer.analyze()` + SigLIP embedding as background
  tasks and `UPDATE`s the row (Phase 2). Eval is explicitly **off the visible hot path** and
  failures are non-fatal.
- **Batch:** `notebooks/02_BATCH_GENERATE.py` via `ai_query()`.
- **Storage:** all fields land in Lakebase `generated_images` columns (`image_gen.py:79`);
  `metrics` is JSONB, issue lists are JSONB arrays.
- **Style guidelines:** `routers/style_guidelines.py` is CRUD over named criteria templates
  that get passed in as `criteria`.

### Key properties to preserve

1. **Enrichment ≠ scoring.** `description`/`tags` are search/UX metadata, not eval. Only the
   `metrics` + flags + critique are truly "evaluation".
2. **Structured, single-shot, cheap-ish.** One model call per image.
3. **Non-blocking + best-effort.** Never blocks gallery visibility; failures degrade gracefully.
4. **Per-request identity.** Analyzer can run under an OBO client (`_create_obo_analyzer`).

---

## 2. What MLflow 3.15.0 actually gives us

Verified against the MLflow CHANGELOG (3.15.0, released 2026-07-31):

> "Multi-modal attachments in LLM judges: `{{ trace }}` judges created with `make_judge()`
> can now *see* images captured in trace spans via a new **`get_span_image` tool**, which
> fetches attachments as base64 data URLs and passes them to multimodal models (Anthropic,
> Gemini, and OpenAI-compatible via litellm)."

Two version floors matter:

- **3.12.0** — "Multimodal Tracing": store multimodal content in spans **as artifact
  attachments** (not inline binary). This is the *producer* side.
- **3.15.0** — the judge `get_span_image` tool. This is the *consumer* side.

**The mechanic that changes our design:** a trace judge is agentic. Given `{{ trace }}` in
its instructions and a multimodal model, it explores the trace and calls `get_span_image` to
fetch attached images on demand. **This only works if the generation was traced and the image
was logged as a span attachment.** We produce zero MLflow traces today, so step one of any
pivot is *instrumentation*, not judging.

**What "attachment" precisely means** (from the MLflow source — `get_span_image.py` and the
multimodal-tracing docs; this bit is easy to get wrong):

- `get_span_image` fetches **only `mlflow-attachment://<id>` reference tokens** found in the
  serialized span (regex `mlflow-attachment://[^\s"'\\]+`). It does **not** read raw bytes and
  does **not** parse inline data URIs.
- Those tokens are produced by **attachment auto-extraction** (env
  `MLFLOW_TRACE_EXTRACT_ATTACHMENTS`, **on by default**, MLflow ≥ 3.12): at export time MLflow
  detects a *recognized* image format in a span's inputs/outputs — a base64 **data URI**, or a
  provider shape like OpenAI **`input_image`** — pulls the bytes into an artifact, and replaces
  them with the token. That same token is what renders as an image in the UI.
- Works for **autolog and manual `@mlflow.trace` spans**, and explicitly for the **Responses
  API**. But only for recognized formats: passing **raw Python `bytes`** into a span is *not*
  extractable — it's dumped verbatim (shows as "image bytes", never becomes an attachment).
- Size cap ~10 MB per image (larger → download link, may not be fetchable) → attach the
  thumbnail, not full-res.

Practical consequence for our capture code: **the image must enter the span as a data URI /
`input_image`, never as raw bytes**, and image bytes must be kept out of judge `inputs`
(a judge that renders `{{ inputs }}` would otherwise inline ~1 MB of base64 and blow the
context window — this actually bit the PoC; see below).

### The judge/scorer surface we'd use

- `make_judge(name, instructions, model)` — custom judge. `{{ trace }}` in instructions →
  trace-exploration mode; **a multimodal `model=` is required** for trace judges.
- `mlflow.genai.evaluate(data=…, predict_fn=…, scorers=[…])` — batch scoring; auto-creates
  a trace per row; writes results to an MLflow run.
- Built-ins: `Safety`, `Guidelines`, `Correctness`, `RelevanceToQuery` — mostly text-shaped;
  our value is in *custom* judges over the image.
- **Alignment (MemAlign)** — `judge.align(traces=<SME-labelled>, optimizer=…)` to bring a
  judge in line with human reviewers. This is the strongest argument for the pivot: our 0–5
  metrics are currently un-calibrated model opinion.
- **Prompt optimization (GEPA)** — `optimize_prompts()` to improve the *generation* prompt
  against a scorer. Directly serves our `improved_prompt` feature, at corpus scale.
- **Production monitoring** — register a scorer, sample a % of live traces.

---

## 3. Mapping current → MLflow

| Today (`ImageAnalysis`) | MLflow shape | Notes |
|---|---|---|
| `metrics.quality` … `safe_content` | one `make_judge` per dimension **or** one multi-`Feedback` judge | Judges emit numeric/categorical `Feedback`; MLflow aggregates (mean/median/p90) across a run |
| `evaluation` (critique) | judge `rationale` | Free with every Feedback |
| `safety_flags` | built-in `Safety` **+** custom multimodal judge | Built-in is text-oriented; image safety needs a `{{ trace }}` judge |
| `brand_conflicts` | custom multimodal `Guidelines`-style judge | Needs the image (attachment) + brand criteria in instructions |
| `missing_or_wrong_elements` | custom judge comparing prompt vs image | `{{ inputs }}` (prompt) + image attachment |
| `improved_prompt` | judge output **or** `optimize_prompts()` (GEPA) | Per-image suggestion → judge; systematic → GEPA |
| `criteria_evaluation` | `Guidelines(guidelines=<style guide>)` or custom judge | Style guidelines become guideline strings/expectations |
| `description`, `tags` | **stays a direct model call** | Enrichment for FTS/UX, not evaluation — don't route through judges |

**Data-format note:** `mlflow.genai.evaluate` wants records shaped
`{"inputs": {...}, "outputs": {...}, "expectations": {...}}` and `predict_fn` receives
**unpacked kwargs**, not a dict. For us the natural `inputs` is the prompt (+ size/quality/
criteria); `outputs` is the volume path / image ref; the image itself rides as a **trace span
attachment**, not as a JSON field.

---

## 4. Proposed architecture (parallel eval layer, not a rip-and-replace)

```
Generation (single / batch)
   │
   ├─(hot path, unchanged)──► ImageAnalyzer.analyze()  → description/tags/quick eval → Lakebase → gallery
   │
   └─(new, opt-in / offline)─► @mlflow.trace generation
                                   └─ log image as SPAN ATTACHMENT (3.12+)
                                   └─ mlflow.genai.evaluate(traces, scorers=[vision judges])
                                          → MLflow experiment run
                                          → (optional) mirror scores back into Lakebase
```

Rationale:
- **Keep product UX synchronous-ish and cheap.** The gallery's tags/description/metrics must
  stay fast and resilient; putting a serving round-trip + trace write on that path is a
  regression waiting to happen.
- **Add MLflow where it's strongest: offline, historical, comparative, calibratable.** Run
  vision judges over batches of traces to get an experiment view, regression comparison
  between prompt versions or `gpt-image-2` vs `gpt-image-1.5`, and (eventually) SME-aligned
  judges.
- **One source of truth for the image:** UC Volume today. Trace attachments would duplicate
  bytes into MLflow artifact storage — fine for sampled eval, not for every image.

### Phasing

- **Phase 0 (this spike):** confirm feasibility. ✅
- **Phase 1 — spike PoC (½–1 day):** implemented as
  [`notebooks/03_MLFLOW_EVAL_POC.py`](../notebooks/03_MLFLOW_EVAL_POC.py). It adds the
  `mlflow[databricks]>=3.15.0` dep, reads a handful of existing corpus images, traces a
  multimodal analysis call so the image is captured on the span, verifies the attachment is
  present, then runs `mlflow.genai.evaluate` with three vision `make_judge` judges
  (prompt-adherence, visual-quality, safe-content) over the sample and compares scores to the
  prior `ImageAnalyzer` metrics as a baseline. Confirms `get_span_image` actually feeds the
  image to the judge in *our* workspace and that a multimodal judge endpoint is reachable.
  **Go/no-go gate: PASSED 2026-07-31** — see "PoC outcome" at the top. All 5 sample images
  scored on all 3 judges with image-grounded rationales.

  Deployment coordinates (from the committed bundle/terraform state on 2026-07-31, defaulted
  in the notebook widgets):
  - workspace `fevm-vision-image-gen.cloud.databricks.com` (id `7474645956599581`)
  - catalog/schema `vision_image_gen_catalog.image_generation`
  - volumes `.../generated_images`, `.../vision_images`
  - serving endpoints `image-generator`, `siglip2-so400m-embeddings`; judge/analyzer model `databricks-gpt-5-5`
  - Lakebase `projects/vision/branches/production/endpoints/primary`, db `databricks-postgres`
  - app `databricks-vision` → `https://databricks-vision-7474645956599581.aws.databricksapps.com`
  - batch job id `1124036977142492`
- **Phase 2:** port the five metrics + flags to judges; build an eval dataset from existing
  `generated_images` rows (we already have prompts + volume paths + prior scores as a
  baseline).
- **Phase 3:** SME labeling session + `align()` to calibrate the quality/brand judges;
  optionally `optimize_prompts()` to systematize `improved_prompt`.
- **Phase 4 (optional):** production monitoring — sample live generations into an experiment.

---

## 5. Risks / open questions

1. **Judge model must support tools + multimodal.** ✅ *Resolved 2026-07-31.* Trace judges
   fetch images via a `get_span_image` **function tool**, and GPT-5.x reject tools + a
   non-`'none'` `reasoning_effort` over `/v1/chat/completions` (all judges errored on first
   run). Fix: pass `inference_params={"reasoning_effort": "none"}` to `make_judge` — then
   **`databricks-gpt-5-5` works**, keeping the eval path on the app's model family
   (Claude works knob-free as an alternative). See "PoC run result" above. The earlier 502
   outage was on the image *generator* tool — a different path from vision *understanding*.
2. **Hot-path latency & cost.** `evaluate()` + trace writes are not free. Keep them off the
   synchronous gallery path (the architecture above does).
3. **Attachment size limits.** 3.x added a size cap on trace attachments; our images can be
   multi-MB (up to 8.3M px). May need to attach the **thumbnail** (we already generate one)
   or a downscaled copy for the judge, and keep full-res in the Volume.
4. **Version floor + new dependency.** MLflow is *not* a dependency today. Need
   `mlflow[databricks]>=3.15.0` for multimodal judges (3.9.0+ only buys UC trace ingestion).
   Adds meaningful surface to `pyproject.toml` / app image.
5. **Duplicate image storage.** Attachments copy bytes into MLflow artifact store. Acceptable
   for sampled eval; do not attach on every single generation.
6. **Enrichment stays put.** Resist the temptation to route `description`/`tags` through
   judges — they're search metadata and want to stay a cheap structured call.
7. **litellm routing.** "OpenAI-compatible via litellm" — confirm our Databricks serving
   endpoints route cleanly as the judge `model` (format `databricks:/<endpoint>`), including
   multimodal payloads, in-workspace.

---

## 6. Recommendation

**Proceed to a Phase-1 PoC, gated on a live multimodal-judge call in the
`databricks-vision` workspace.** The 3.15.0 feature genuinely unlocks the part we can't do
well today — *calibrated, comparable, historical* image evaluation — and aligns with the
`make_judge`/`evaluate`/`align`/`optimize` boundary we already use elsewhere. But adopt it as
an **additive offline/opt-in layer**, not a replacement for the inline enrichment call that
powers the gallery. The single biggest unknown is not the API (confirmed) but whether a
multimodal judge endpoint is reachable and healthy in this workspace right now — so the PoC
leads with that.

---

### Appendix: sketch of a vision judge (illustrative, not wired in)

```python
import mlflow
from mlflow.genai.judges import make_judge

# Generation is traced; the PNG (or its thumbnail) is logged as a span attachment
# so the judge's get_span_image tool can fetch it.

prompt_adherence = make_judge(
    name="prompt_adherence",
    instructions="""
    You are evaluating an AI-generated image against the prompt that produced it.
    Prompt: {{ inputs }}
    Inspect the generated image in {{ trace }} (use the image attachment on the
    generation span). Score how completely and correctly every element of the prompt
    is present in the image.
    Respond with an integer 0-5 (5 = every element present and correct).
    """,
    model="databricks:/databricks-gpt-5-5",  # multimodal; REQUIRED for {{ trace }} judges
)

results = mlflow.genai.evaluate(
    data=eval_dataset,          # [{"inputs": {"prompt": ...}, ...}] with traced generations
    scorers=[prompt_adherence], # + safety / brand / missing-elements judges
)
```
