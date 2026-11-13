"""API routes against a real Postgres + pgvector database (the Lakebase stand-in)."""
from __future__ import annotations

import json
from io import BytesIO

import pytest
from PIL import Image

from databricks_vision.backend.core._eval import DEFAULT_CRITERIA
from tests.integration.conftest import execute, fetch

pytestmark = pytest.mark.integration


def _seed_batch(db, batch_id: str, *, mode: str = "single", folder: str = "default", images: int = 2) -> None:
    execute(
        db,
        "INSERT INTO batch_runs (batch_id, batch_name, batch_mode, input_volume_path, prompt_template, status, folder)"
        " VALUES (%s, %s, %s, '', 'a prompt', 'succeeded', %s)",
        (batch_id, f"batch {batch_id}", mode, folder),
    )
    for i in range(1, images + 1):
        execute(
            db,
            "INSERT INTO generated_images (id, batch_id, image_name, prompt, status, volume_path, tags, metrics,"
            " thumbnail_path) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)",
            (
                i, batch_id, f"img_{i}", f"prompt {i}", "success" if i % 2 else "failed",
                f"/Volumes/c/s/generated_images/{batch_id}/img_{i}.png",
                json.dumps(["fox", "snow"]), json.dumps({"quality": 4}),
                f"/Volumes/c/s/generated_images/{batch_id}/img_{i}_thumb.jpeg",
            ),
        )


def test_health_with_database(db_client):
    body = db_client.get("/api/health").json()
    assert body["status"] == "ok" and body["db"] is True


# --- eval criteria ----------------------------------------------------------------------


def test_list_eval_criteria(db_client):
    r = db_client.get("/api/eval-criteria")
    assert r.status_code == 200
    rows = r.json()
    assert [c["key"] for c in rows] == ["quality", "prompt", "text", "safe", "custom"]
    assert rows[-1]["is_custom"] and rows[-1]["enabled"] is False


def test_patch_rejects_instructions_without_trace(db_client, db):
    before = fetch(db, "SELECT instructions FROM eval_criteria WHERE key = 'quality'")[0]["instructions"]
    r = db_client.patch("/api/eval-criteria/quality", json={"instructions": "Rate it 0-5"})
    assert r.status_code == 400 and "{{ trace }}" in r.json()["detail"]
    assert fetch(db, "SELECT instructions FROM eval_criteria WHERE key = 'quality'")[0]["instructions"] == before


def test_patch_builtin_label_rejected(db_client):
    r = db_client.patch("/api/eval-criteria/quality", json={"label": "Looks"})
    assert r.status_code == 400


def test_patch_unknown_criterion_404(db_client):
    assert db_client.patch("/api/eval-criteria/nope", json={"enabled": True}).status_code == 404


def test_enable_and_relabel_custom_criterion(db_client):
    r = db_client.patch(
        "/api/eval-criteria/custom",
        json={"label": "  Brand fit ", "enabled": True, "instructions": "Does {{ trace }} fit the brand? 0-5"},
    )
    assert r.status_code == 200
    assert r.json() == {
        "key": "custom", "label": "Brand fit", "instructions": "Does {{ trace }} fit the brand? 0-5",
        "is_custom": True, "enabled": True,
    }


def test_reset_restores_default_instructions(db_client):
    db_client.patch("/api/eval-criteria/text", json={"instructions": "Custom text check for {{ trace }}"})
    r = db_client.post("/api/eval-criteria/text/reset")
    assert r.status_code == 200
    default = next(c for c in DEFAULT_CRITERIA if c["key"] == "text")
    assert r.json()["instructions"] == default["instructions"]


# --- style guidelines / brand kits ------------------------------------------------------


def test_style_guideline_crud(db_client):
    r = db_client.post(
        "/api/style-guidelines",
        json={"name": " Acme ", "body": "Friendly tone", "palette": ["#1a73e8", " #1A73E8 ", "#fff"]},
    )
    assert r.status_code == 200, r.text
    kit = r.json()
    assert kit["name"] == "Acme"
    assert kit["palette"] == ["#1A73E8", "#FFF"]  # trimmed, upper-cased, de-duplicated

    r = db_client.patch(f"/api/style-guidelines/{kit['id']}", json={"typography": "Inter", "is_default": True})
    assert r.status_code == 200 and r.json()["typography"] == "Inter" and r.json()["is_default"] is True

    assert [g["name"] for g in db_client.get("/api/style-guidelines").json()] == ["Acme"]

    assert db_client.delete(f"/api/style-guidelines/{kit['id']}").status_code == 200
    assert db_client.delete(f"/api/style-guidelines/{kit['id']}").status_code == 404


def test_style_guideline_rejects_bad_palette(db_client):
    r = db_client.post("/api/style-guidelines", json={"name": "Bad", "palette": ["blue"]})
    assert r.status_code == 400


def test_setting_a_new_default_clears_the_old_one(db_client):
    a = db_client.post("/api/style-guidelines", json={"name": "A", "is_default": True}).json()
    b = db_client.post("/api/style-guidelines", json={"name": "B", "is_default": True}).json()
    kits = {g["name"]: g for g in db_client.get("/api/style-guidelines").json()}
    assert kits["B"]["is_default"] and not kits["A"]["is_default"]
    db_client.patch(f"/api/style-guidelines/{a['id']}", json={"is_default": True})
    kits = {g["name"]: g for g in db_client.get("/api/style-guidelines").json()}
    assert kits["A"]["is_default"] and not kits["B"]["is_default"]
    assert b["id"] != a["id"]


def test_brand_kit_logo_roundtrip(db_client, fake_ws):
    kit = db_client.post("/api/style-guidelines", json={"name": "Logo kit"}).json()
    png = BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(png, format="PNG")

    r = db_client.post(
        f"/api/style-guidelines/{kit['id']}/logo",
        files={"logo": ("logo.png", png.getvalue(), "image/png")},
    )
    assert r.status_code == 200, r.text
    path = r.json()["logo_path"]
    assert path == f"/Volumes/test_catalog/test_schema/vision_images/brand-kits/{kit['id']}/logo.png"
    assert fake_ws.files.store[path] == png.getvalue()

    r = db_client.get(f"/api/style-guidelines/{kit['id']}/logo")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == png.getvalue()

    assert db_client.delete(f"/api/style-guidelines/{kit['id']}/logo").json()["logo_path"] == ""


def test_logo_rejects_non_images(db_client):
    kit = db_client.post("/api/style-guidelines", json={"name": "Text kit"}).json()
    r = db_client.post(
        f"/api/style-guidelines/{kit['id']}/logo", files={"logo": ("x.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 400


# --- folders + gallery ------------------------------------------------------------------


def test_folder_lifecycle(db_client, db, fake_ws):
    folders = db_client.get("/api/folders").json()
    assert [(f["name"], f["image_count"]) for f in folders] == [("default", 0)]

    r = db_client.post("/api/folders", json={"name": "Summer Campaign"})
    assert r.status_code == 200 and r.json()["name"] == "summer_campaign"
    # Idempotent: creating it again returns the same folder.
    assert db_client.post("/api/folders", json={"name": "summer campaign"}).json()["id"] == r.json()["id"]

    _seed_batch(db, "aaaa0001", folder="summer_campaign", images=3)
    counts = {f["name"]: f["image_count"] for f in db_client.get("/api/folders").json()}
    assert counts == {"default": 0, "summer_campaign": 2}  # only status='success' rows count

    assert db_client.delete("/api/folders/default").status_code == 400
    r = db_client.delete("/api/folders/summer_campaign")
    assert r.status_code == 200 and r.json()["rows_deleted"] == 3
    assert fetch(db, "SELECT COUNT(*) AS n FROM generated_images")[0]["n"] == 0  # FK cascade
    assert len(fake_ws.files.deleted) == 6  # every image + thumbnail path, best-effort


def test_gallery_lists_successful_images_with_decoded_json(db_client, db):
    _seed_batch(db, "bbbb0001", images=3)
    r = db_client.get("/api/gallery")
    assert r.status_code == 200
    images = r.json()
    assert sorted(i["image_name"] for i in images) == ["img_1", "img_3"]
    assert all(i["tags"] == ["fox", "snow"] and i["metrics"] == {"quality": 4} for i in images)
    assert all(i["folder"] == "default" for i in images)


def test_gallery_filters(db_client, db):
    _seed_batch(db, "cccc0001", mode="single", folder="default", images=1)
    _seed_batch(db, "cccc0002", mode="multi_image", folder="default", images=1)
    execute(db, "INSERT INTO folders (name) VALUES ('other')")
    _seed_batch(db, "cccc0003", mode="compose", folder="other", images=1)

    def ids(**params):
        return sorted(i["batch_id"] for i in db_client.get("/api/gallery", params=params).json())

    assert ids() == ["cccc0001", "cccc0002", "cccc0003"]
    assert ids(mode="single") == ["cccc0001", "cccc0003"]  # every single-image mode
    assert ids(mode="multi_image") == ["cccc0002"]
    assert ids(folder="other") == ["cccc0003"]
    assert ids(batch_id="cccc0002") == ["cccc0002"]
    assert len(db_client.get("/api/gallery", params={"limit": 1, "page": 2}).json()) == 1


# --- batches ----------------------------------------------------------------------------


def test_list_batches_counts_images(db_client, db):
    _seed_batch(db, "dddd0001", mode="multi_image", images=3)
    batches = db_client.get("/api/batches").json()
    assert len(batches) == 1
    assert batches[0]["total_images"] == 3 and batches[0]["successful_images"] == 2


def test_batch_detail_includes_version_counts(db_client, db):
    _seed_batch(db, "eeee0001", mode="multi_image", images=2)
    execute(
        db,
        "INSERT INTO image_versions (batch_id, image_id, version, prompt, status) VALUES"
        " ('eeee0001', 1, 1, 'v1', 'success'), ('eeee0001', 1, 2, 'v2', 'success')",
    )
    r = db_client.get("/api/batches/eeee0001")
    assert r.status_code == 200
    body = r.json()
    assert body["batch"]["batch_id"] == "eeee0001"
    versions = {i["image_name"]: i["version_count"] for i in body["images"]}
    assert versions == {"img_1": 2, "img_2": 0}


def test_unknown_batch_404(db_client):
    assert db_client.get("/api/batches/zzzz9999").status_code == 404
