# Databricks notebook source
# MAGIC %md
# MAGIC # Batch Image Generation
# MAGIC
# MAGIC Single-notebook pipeline that:
# MAGIC 1. Reads input images from a UC Volume and base64-encodes them
# MAGIC 2. Runs `ai_query()` against the `image-generator` serving endpoint
# MAGIC 3. Saves generated images to an output UC Volume
# MAGIC 4. Syncs result rows to Lakebase for the app to serve
# MAGIC
# MAGIC Analyzer + SigLIP embedding (eval columns + semantic search) is NOT run
# MAGIC here — the app's `/api/gallery/analyze` endpoint backfills those fields
# MAGIC on demand. Keeping the job lean cuts the serverless cold-start.
# MAGIC
# MAGIC **Parameters** (passed from the Jobs API; see databricks.yml for the full list):
# MAGIC - `batch_id`, `batch_mode`, `input_volume_path`, `source_image_path`,
# MAGIC   `reference_image_path`, `prompt_template`, `variations_json`, `batch_name`
# MAGIC - `size`, `quality`, `image_model`, `output_format`, `background` —
# MAGIC   generation tool params
# MAGIC - `catalog`, `schema_name`, `serving_endpoint_name`, `lakebase_endpoint`
# MAGIC   — workspace coords

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("batch_id", "", "Batch ID")
dbutils.widgets.text("batch_mode", "multi_image", "Batch Mode")
dbutils.widgets.text("input_volume_path", "", "Input Volume Path")
dbutils.widgets.text("source_image_path", "", "Source Image Path")
dbutils.widgets.text("reference_image_path", "", "Reference Image Path")
dbutils.widgets.text("prompt_template", "", "Prompt Template")
dbutils.widgets.text("variations_json", "[]", "Variations JSON")
dbutils.widgets.text("batch_name", "", "Batch Name")
dbutils.widgets.text("size", "1024x1024", "Size")
dbutils.widgets.text("quality", "low", "Quality")
dbutils.widgets.text("image_model", "gpt-image-2", "Image Model")
dbutils.widgets.text("output_format", "png", "Output Format")
dbutils.widgets.text("background", "opaque", "Background")
dbutils.widgets.text("catalog", "", "Catalog")
dbutils.widgets.text("schema_name", "", "Schema")
dbutils.widgets.text("serving_endpoint_name", "image-generator", "Serving Endpoint")
dbutils.widgets.text("lakebase_endpoint", "", "Lakebase Endpoint Name")

batch_id = dbutils.widgets.get("batch_id")
batch_mode = dbutils.widgets.get("batch_mode") or "multi_image"
input_volume_path = dbutils.widgets.get("input_volume_path").strip()
source_image_path = dbutils.widgets.get("source_image_path").strip()
reference_image_path = dbutils.widgets.get("reference_image_path").strip()
prompt_template = dbutils.widgets.get("prompt_template")
variations_json = dbutils.widgets.get("variations_json") or "[]"
batch_name = dbutils.widgets.get("batch_name") or ""
size = dbutils.widgets.get("size") or "1024x1024"
quality = dbutils.widgets.get("quality") or "low"
image_model = dbutils.widgets.get("image_model") or "gpt-image-2"
output_format = dbutils.widgets.get("output_format") or "png"
background = dbutils.widgets.get("background") or "opaque"
catalog = dbutils.widgets.get("catalog")
schema_name = dbutils.widgets.get("schema_name")
serving_endpoint_name = dbutils.widgets.get("serving_endpoint_name")
lakebase_endpoint = dbutils.widgets.get("lakebase_endpoint")

output_volume = f"/Volumes/{catalog}/{schema_name}/generated_images"

assert batch_id, "batch_id is required"
if batch_mode == "variations":
    assert source_image_path, "source_image_path is required for variations mode"
else:
    assert input_volume_path, "input_volume_path is required"
    assert prompt_template, "prompt_template is required"

print(f"Batch: {batch_id} (mode={batch_mode})")
print(f"Input: {input_volume_path or source_image_path}")
print(f"Reference: {reference_image_path or '(none)'}")
print(f"Tool params: size={size}, quality={quality}, model={image_model}, format={output_format}, bg={background}")
if batch_mode == "variations":
    print(f"Variations: {variations_json[:120]}...")
else:
    print(f"Prompt: {prompt_template[:80]}...")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load & prepare input images

# COMMAND ----------

import base64
import json as _json
import re
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, StructType, StructField, IntegerType
from pyspark.sql.window import Window

MAX_ENDPOINT_CONCURRENCY = 16

# Load reference image if provided
reference_b64 = None
if reference_image_path:
    try:
        df_ref = spark.read.format("binaryFile").load(reference_image_path)
        reference_b64 = base64.b64encode(df_ref.collect()[0]["content"]).decode("utf-8")
        print(f"Reference image loaded: {len(reference_b64):,} chars")
    except Exception as e:
        print(f"Warning: Could not load reference image: {e}")

if batch_mode == "variations":
    variations = _json.loads(variations_json)

    df_source = spark.read.format("binaryFile").load(source_image_path)
    source_b64 = base64.b64encode(df_source.collect()[0]["content"]).decode("utf-8")
    print(f"Source image loaded: {len(source_b64):,} chars")

    source_image_name = re.sub(r"\.\w+$", "", source_image_path.rsplit("/", 1)[-1]).replace("_", " ")

    rows = []
    for i, v in enumerate(variations, 1):
        safe_name = re.sub(r"[^a-z0-9_]+", "_", v["label"].lower()).strip("_")
        image_name = f"{i:02d}_{safe_name}"
        prompt = v["prompt"].replace("{image_name}", source_image_name) if "{image_name}" in v["prompt"] else v["prompt"]
        rows.append((i, batch_id, image_name, v["label"], source_image_path, source_b64, reference_b64 or "", prompt))

    schema = StructType([
        StructField("id", IntegerType()),
        StructField("batch_id", StringType()),
        StructField("image_name", StringType()),
        StructField("variation_label", StringType()),
        StructField("input_image_path", StringType()),
        StructField("input_image_b64", StringType()),
        StructField("reference_image_b64", StringType()),
        StructField("prompt", StringType()),
    ])
    df_inputs = spark.createDataFrame(rows, schema)

else:
    encode_b64 = F.udf(lambda b: base64.b64encode(b).decode("utf-8"), StringType())

    df_images = (
        spark.read.format("binaryFile")
        .option("pathGlobFilter", "*.{png,jpg,jpeg}")
        .load(f"{input_volume_path}/*")
    )

    window_spec = Window.orderBy(F.monotonically_increasing_id())
    df_images = (
        df_images
        .withColumn("id", F.row_number().over(window_spec))
        .withColumn("image_name", F.regexp_extract(F.col("path"), r"/([^/]+)\.\w+$", 1))
    )

    df_images = df_images.withColumn("input_image_b64", encode_b64(F.col("content")))

    @F.udf(StringType())
    def build_prompt(image_name):
        return prompt_template.replace("{image_name}", image_name.replace("_", " ")).strip()

    df_inputs = (
        df_images
        # F.lit(None) creates a void-typed column; ai_query rejects void.
        # Coerce to "" so the column always carries StringType.
        .withColumn("reference_image_b64", F.lit(reference_b64 or ""))
        .withColumn("prompt", build_prompt(F.col("image_name")))
        .withColumn("batch_id", F.lit(batch_id))
        .withColumn("variation_label", F.lit(""))
        .withColumn("input_image_path", F.regexp_replace(F.col("path"), "^dbfs:", ""))
        .select("id", "batch_id", "image_name", "variation_label", "input_image_path", "input_image_b64", "reference_image_b64", "prompt")
    )

# Tool params travel as per-row columns so ai_query's named_struct can pick them up.
df_inputs = (
    df_inputs
    .withColumn("size", F.lit(size))
    .withColumn("quality", F.lit(quality))
    .withColumn("image_model", F.lit(image_model))
    .withColumn("output_format", F.lit(output_format))
    .withColumn("background", F.lit(background))
)

num_rows = df_inputs.count()
num_partitions = min(num_rows, MAX_ENDPOINT_CONCURRENCY)
df_inputs.repartition(num_partitions).createOrReplaceTempView("generation_inputs")

print(f"Prepared {num_rows} {'variations' if batch_mode == 'variations' else 'images'} in {num_partitions} partitions")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Run ai_query()

# COMMAND ----------

df_results = spark.sql(f"""
    SELECT
        id, batch_id, image_name, variation_label, input_image_path, prompt,
        size, quality, image_model, output_format, background,
        result.result.output_image_b64,
        COALESCE(result.result.status, 'error') AS status,
        result.errorMessage AS error_message
    FROM (
        SELECT id, batch_id, image_name, variation_label, input_image_path, prompt,
            size, quality, image_model, output_format, background,
            ai_query(
                '{serving_endpoint_name}',
                request => named_struct(
                    'input_image_b64', input_image_b64,
                    'reference_image_b64', reference_image_b64,
                    'prompt', prompt,
                    'size', size,
                    'quality', quality,
                    'image_model', image_model,
                    'output_format', output_format,
                    'background', background
                ),
                returnType => 'STRUCT<output_image_b64: STRING, status: STRING>',
                failOnError => false
            ) AS result
        FROM generation_inputs
    )
""")

results = df_results.collect()
successful = sum(1 for r in results if r["status"] == "success")
print(f"Generated: {successful}/{len(results)} successful")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Save images to UC Volume

# COMMAND ----------

_format_to_ext = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp"}
output_ext = _format_to_ext.get(output_format.lower(), ".jpeg")

batch_output_path = f"{output_volume}/{batch_id}"
dbutils.fs.mkdirs(batch_output_path.replace("/Volumes/", "dbfs:/Volumes/"))

volume_paths = {}
for row in results:
    if row["output_image_b64"] and row["status"] == "success":
        img_bytes = base64.b64decode(row["output_image_b64"])
        filename = f"{row['image_name']}_generated{output_ext}"
        path = f"{batch_output_path}/{filename}"
        with open(path, "wb") as f:
            f.write(img_bytes)
        volume_paths[row["id"]] = path

print(f"Saved {len(volume_paths)}/{len(results)} images to {batch_output_path}/")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Sync results to Lakebase
# MAGIC
# MAGIC Analyzer + SigLIP embedding (Phase 2) is intentionally NOT run here —
# MAGIC the app's `/api/gallery/analyze` endpoint backfills those fields for the
# MAGIC batch (the UI triggers it when the batch detail page opens). Keeping
# MAGIC the job lean cuts the per-run cold-start: only databricks-sdk +
# MAGIC psycopg2-binary need to install.

# COMMAND ----------

import psycopg2
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
cred = w.postgres.generate_database_credential(endpoint=lakebase_endpoint)
branch_path = "/".join(lakebase_endpoint.split("/")[:4])
endpoints = list(w.postgres.list_endpoints(parent=branch_path))
pg_host = endpoints[0].status.hosts.host if endpoints else ""

conn = psycopg2.connect(
    host=pg_host,
    dbname="databricks_postgres",
    user=w.current_user.me().user_name,
    password=cred.token,
    sslmode="require",
)

total = len(results)

with conn:
    with conn.cursor() as cur:
        # Idempotent re-run: clear any prior rows for this batch.
        cur.execute("DELETE FROM generated_images WHERE batch_id = %s", (batch_id,))

        for row in results:
            vpath = volume_paths.get(row["id"])
            cur.execute(
                """INSERT INTO generated_images
                   (id, batch_id, image_name, prompt, status, error_message, volume_path,
                    variation_label, input_image_path, image_model, size)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    row["id"], row["batch_id"], row["image_name"], row["prompt"],
                    row["status"], row["error_message"], vpath,
                    row["variation_label"], row["input_image_path"],
                    image_model, size,
                ),
            )

        cur.execute(
            """UPDATE batch_runs
               SET status = 'completed',
                   successful_images = %s,
                   total_images = %s,
                   output_volume_path = %s
               WHERE batch_id = %s""",
            (successful, total, batch_output_path, batch_id),
        )
conn.close()

print(f"Synced {total} rows to Lakebase ({successful} successful)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

print(f"Batch {batch_id}: {successful}/{total} images generated")
print(f"  Volume:   {batch_output_path}/")
print(f"  Lakebase: synced (analyze/embed pending — run from the gallery UI)")
