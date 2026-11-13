import urllib.request

from databricks.sdk.service.iam import User as UserOut
from fastapi import Request
from pydantic import BaseModel

from .core import Dependencies, create_router
from .models import AppConfigOut, HealthOut, VersionOut
from .routers import (
    batch_images_router,
    batches_router,
    eval_criteria_router,
    gallery_router,
    generate_router,
    search_router,
    settings_router,
    style_guidelines_router,
    volumes_router,
)

router = create_router()

router.include_router(batches_router)
router.include_router(batch_images_router)
router.include_router(search_router)
router.include_router(volumes_router)
router.include_router(gallery_router)
router.include_router(generate_router)
router.include_router(settings_router)
router.include_router(style_guidelines_router)
router.include_router(eval_criteria_router)


@router.get("/version", response_model=VersionOut, operation_id="version")
async def version():
    return VersionOut.from_metadata()


@router.get("/health", response_model=HealthOut, operation_id="health")
def health(request: Request):
    """Liveness + dependency check used by the post-deploy smoke test. Always 200 so a
    degraded app still reports *what* is down; callers assert on the fields."""
    pool = getattr(request.app.state, "db_pool", None)
    db_ok = False
    if pool is not None:
        try:
            with pool.connection(timeout=5) as conn:
                conn.execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False
    eval_enabled = getattr(request.app.state, "image_evaluator", None) is not None
    return HealthOut(
        status="ok" if db_ok else "degraded",
        version=VersionOut.from_metadata().version,
        db=db_ok,
        eval_enabled=eval_enabled,
    )


@router.get("/current-user", response_model=UserOut, operation_id="currentUser")
def me(user_ws: Dependencies.UserClient):
    return user_ws.current_user.me()


_cached_org_id: str | None = None


def _fetch_org_id(ws) -> str:
    global _cached_org_id
    if _cached_org_id is not None:
        return _cached_org_id
    try:
        headers: dict = {}
        ws.config.authenticate(headers)
        if not headers.get("Authorization"):
            _cached_org_id = ""
            return ""
        url = f"{ws.config.host.rstrip('/')}/api/2.0/clusters/list-node-types"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            _cached_org_id = resp.getheader("x-databricks-org-id") or ""
            return _cached_org_id
    except Exception:
        _cached_org_id = ""
        return ""


@router.get("/app-config", response_model=AppConfigOut, operation_id="getAppConfig")
def get_app_config(ws: Dependencies.Client):
    workspace_url = ws.config.host or ""
    org_id = _fetch_org_id(ws)
    return AppConfigOut(workspace_url=workspace_url, org_id=org_id)


