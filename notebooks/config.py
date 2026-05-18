# Workspace-specific configuration consumed by notebooks/01_MODEL_DEPLOY.py.
#
# Edit CATALOG and SCHEMA to match the catalog/schema you created during the
# one-time bootstrap (see DEPLOY.md §2b). Notebooks 00 and 02 take these values
# via Databricks widgets instead.

CATALOG = "<your-catalog>"
SCHEMA = "<your-schema>"

# Volumes — defaults (overridable via notebook widgets where applicable)
DEFAULT_INPUT_VOLUME = f"/Volumes/{CATALOG}/{SCHEMA}/vision_images"
DEFAULT_REFERENCE_IMAGE = ""
OUTPUT_VOLUME_NAME = "generated_images"
OUTPUT_VOLUME = f"/Volumes/{CATALOG}/{SCHEMA}/{OUTPUT_VOLUME_NAME}"

# Tables
GENERATION_INPUTS_TABLE = f"{CATALOG}.{SCHEMA}.generation_inputs"
GENERATED_IMAGES_TABLE = f"{CATALOG}.{SCHEMA}.generated_images"

# Model & Endpoint
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.image_generator"
ENDPOINT_NAME = "image-generator"

# Default prompt template — illustrative only; users typically override this
# via the app UI. Available placeholders: {image_name}.
DEFAULT_PROMPT_TEMPLATE = """
Create a high-quality, professional product photograph featuring the {image_name}.

Composition: clean studio setup, soft directional lighting, neutral backdrop, shallow depth of field. The subject is centred and well-lit, with natural shadows. No text overlays, no watermarks.
"""
