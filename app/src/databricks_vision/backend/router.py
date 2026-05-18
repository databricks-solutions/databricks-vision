import urllib.request

from databricks.sdk.service.iam import User as UserOut
from pydantic import BaseModel

from .core import Dependencies, create_router
from .models import AppConfigOut, VersionOut
from .routers import (
    batch_images_router,
    batches_router,
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


@router.get("/version", response_model=VersionOut, operation_id="version")
async def version():
    return VersionOut.from_metadata()


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


