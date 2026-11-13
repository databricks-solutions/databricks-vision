"""Post-deploy smoke test for a deployed databricks-vision app (run last by scripts/deploy.sh).

1. Waits until the app's compute is ACTIVE, the app is RUNNING and its active deployment
   SUCCEEDED (fails fast on CRASHED / FAILED).
2. Calls the app as the deploying identity (the same profile / env auth as the deploy):
     GET /api/health                  -> status "ok", db true (Lakebase reachable from the app)
     GET /api/settings/image-models   -> non-empty
     GET /api/eval-criteria           -> the 5 criteria (schema bootstrapped + SP grants work)
3. --generate (opt-in, costs one low-quality image call): POST /api/generate and wait for the
   SSE stream to deliver an image. Exercises model serving, the app SP's serving permissions and
   the Volume write path. The image lands in the target's gallery (default folder).

Usage (via run_py in scripts/_common.sh, or any env with databricks-sdk):
    python3 scripts/smoke_test.py --app databricks-vision-dev [--generate] [--timeout 900]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.apps import AppDeploymentState, ApplicationState, ComputeState


def mask(value: str | None) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true" and value:
        print(f"::add-mask::{value}", flush=True)


def fail(msg: str) -> None:
    print(f"SMOKE TEST FAILED: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def wait_until_running(w: WorkspaceClient, name: str, timeout_s: int):
    deadline = time.monotonic() + timeout_s
    last = None
    while True:
        app = w.apps.get(name)
        compute = app.compute_status.state if app.compute_status else None
        status = app.app_status.state if app.app_status else None
        deployment = (
            app.active_deployment.status.state
            if app.active_deployment and app.active_deployment.status else None
        )
        pending = app.pending_deployment is not None and app.pending_deployment.status is not None and (
            app.pending_deployment.status.state == AppDeploymentState.IN_PROGRESS
        )
        state = (compute, status, deployment, pending)
        if state != last:
            print(f"  compute={getattr(compute, 'name', compute)} app={getattr(status, 'name', status)} "
                  f"deployment={getattr(deployment, 'name', deployment)} pending={pending}", flush=True)
            last = state
        if compute == ComputeState.ACTIVE and status == ApplicationState.RUNNING \
                and deployment == AppDeploymentState.SUCCEEDED and not pending:
            return app
        if status == ApplicationState.CRASHED:
            fail(f"app crashed: {app.app_status.message}  (check: databricks apps logs {name})")
        if deployment in (AppDeploymentState.FAILED, AppDeploymentState.CANCELLED):
            fail(f"active deployment {deployment.name}: {app.active_deployment.status.message}")
        if compute == ComputeState.ERROR:
            fail(f"app compute in ERROR: {app.compute_status.message}")
        if time.monotonic() > deadline:
            fail(f"app not RUNNING after {timeout_s}s (last state: {state})")
        time.sleep(10)


class AppClient:
    def __init__(self, w: WorkspaceClient, base_url: str):
        self.w = w
        self.base = base_url.rstrip("/")

    def _headers(self) -> dict:
        headers = self.w.config.authenticate()  # works for U2M, M2M and GitHub OIDC alike
        if "Authorization" not in headers:
            fail("could not obtain an OAuth token for the deploying identity")
        return headers

    def request(self, method: str, path: str, data: dict | None = None, timeout: int = 60):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        headers = self._headers()
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            fail(f"{method} {path} -> HTTP {exc.code}: {detail}")

    def get_json(self, path: str):
        with self.request("GET", path) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read()
        if "json" not in ctype:
            # A login page instead of JSON means the token was not accepted by the Apps proxy.
            fail(f"GET {path} returned {ctype or 'no content type'}, not JSON (auth redirect?)")
        return json.loads(raw)


def check_endpoints(client: AppClient) -> None:
    health = client.get_json("/api/health")
    print(f"  /api/health -> {health}", flush=True)
    if health.get("status") != "ok" or not health.get("db"):
        fail(f"health is degraded: {health}")

    models = client.get_json("/api/settings/image-models")
    if not models:
        fail("/api/settings/image-models returned no models")
    print(f"  /api/settings/image-models -> {len(models)} models", flush=True)

    criteria = client.get_json("/api/eval-criteria")
    keys = [c.get("key") for c in criteria]
    if keys != ["quality", "prompt", "text", "safe", "custom"]:
        fail(f"/api/eval-criteria returned {keys}")
    print(f"  /api/eval-criteria -> {len(criteria)} criteria", flush=True)


def check_generation(client: AppClient) -> None:
    form = {"prompt": "Smoke test: a single flat blue square on a white background", "n": "1",
            "quality": "low", "size": "1024x1024", "output_format": "jpeg", "background": "opaque"}
    print("  POST /api/generate (1 low-quality image) ...", flush=True)
    event = None
    with client.request("POST", "/api/generate", data=form, timeout=300) as resp:
        for raw in resp:
            line = raw.decode(errors="replace").strip()
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event in ("done", "error", "complete"):
                data = json.loads(line.split(":", 1)[1])
                if event == "error":
                    fail(f"generation error: {data.get('error')}")
                if event == "done":
                    print(f"  generated image ({len(data.get('image_b64', '')) * 3 // 4} bytes)", flush=True)
                if event == "complete":
                    if not data.get("count"):
                        fail("generation completed with 0 images")
                    return
    fail("SSE stream ended without a 'complete' event")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app", required=True, help="Databricks App name")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds to wait for RUNNING (default 900)")
    parser.add_argument("--generate", action="store_true", help="Also generate one low-quality image")
    args = parser.parse_args()

    w = WorkspaceClient()
    print(f"Smoke testing app {args.app} ...", flush=True)
    app = wait_until_running(w, args.app, args.timeout)
    if not app.url:
        fail("app has no URL")
    mask(app.url)
    client = AppClient(w, app.url)
    check_endpoints(client)
    if args.generate:
        check_generation(client)
    print("Smoke test passed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
