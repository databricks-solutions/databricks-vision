"""The app assembles, exposes its routes, and serves the DB-free endpoints."""
from __future__ import annotations

from image_gen import FORMAT_PRESETS, enabled_image_models

EXPECTED_ROUTES = {
    ("GET", "/api/version"),
    ("GET", "/api/health"),
    ("GET", "/api/app-config"),
    ("GET", "/api/current-user"),
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/settings/image-models"),
    ("GET", "/api/settings/formats"),
    ("GET", "/api/gallery"),
    ("GET", "/api/folders"),
    ("POST", "/api/folders"),
    ("GET", "/api/batches"),
    ("POST", "/api/batches"),
    ("GET", "/api/batches/{batch_id}"),
    ("GET", "/api/eval-criteria"),
    ("PATCH", "/api/eval-criteria/{key}"),
    ("GET", "/api/style-guidelines"),
    ("POST", "/api/style-guidelines"),
    ("GET", "/api/search"),
}


def test_expected_routes_registered(app):
    # Read routes from the OpenAPI spec: FastAPI's `app.routes` internals change between
    # versions (newer releases nest included routers), and production installs the latest.
    registered = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    missing = EXPECTED_ROUTES - registered
    assert not missing, f"routes missing from the app: {sorted(missing)}"


def test_openapi_schema_builds(app):
    # Catches broken Pydantic models / response_model declarations at import-free cost.
    spec = app.openapi()
    assert spec["paths"]
    operation_ids = [op["operationId"] for path in spec["paths"].values() for op in path.values()]
    assert len(operation_ids) == len(set(operation_ids)), "duplicate operation_id (breaks the UI client)"


def test_version(client):
    r = client.get("/api/version")
    assert r.status_code == 200 and r.json()["version"]


def test_health_without_database_reports_degraded(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded" and body["db"] is False and body["eval_enabled"] is False


def test_current_user_uses_workspace_client(client):
    r = client.get("/api/current-user")
    assert r.status_code == 200 and r.json()["user_name"] == "tester@example.com"


def test_app_config(client):
    r = client.get("/api/app-config")
    assert r.status_code == 200
    assert r.json()["workspace_url"] == "https://example.cloud.databricks.com"


def test_get_settings_reflects_config(client, app_config):
    r = client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["image_model"] == app_config.image_model
    assert body["vision_volume"] == "/Volumes/test_catalog/test_schema/vision_images"


def test_put_settings_updates_config(client, app_config):
    r = client.put("/api/settings", json={"image_model": "gpt-image-2", "default_quality": "high"})
    assert r.status_code == 200
    assert r.json()["image_model"] == "gpt-image-2"
    assert app_config.image_model == "gpt-image-2" and app_config.default_quality == "high"


def test_put_settings_rejects_unknown_image_model(client, app_config):
    before = app_config.image_model
    r = client.put("/api/settings", json={"image_model": "not-a-model"})
    assert r.status_code == 400
    assert app_config.image_model == before


def test_image_models_endpoint_matches_presets(client):
    r = client.get("/api/settings/image-models")
    assert r.status_code == 200
    models = r.json()
    assert [m["id"] for m in models] == enabled_image_models()
    assert all(m["qualities"] for m in models)


def test_format_presets_endpoint(client):
    r = client.get("/api/settings/formats")
    assert r.status_code == 200
    assert {f["key"] for f in r.json()} == set(FORMAT_PRESETS)
