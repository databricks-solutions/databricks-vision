import logging

from fastapi import APIRouter, HTTPException, Response

from ..core import Dependencies
from ..models import CatalogOut, FileEntryOut, SchemaOut, VolumeOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/volumes", tags=["volumes"])

_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _image_media_type(path: str) -> str:
    """Validate *path* as a raster image under /Volumes/ and return its media type (400 if not)."""
    if not path.startswith("/Volumes/") or ".." in path.split("/"):
        raise HTTPException(400, "Path must be a file under /Volumes/")
    ext = path[path.rfind("."):].lower() if "." in path.rsplit("/", 1)[-1] else ""
    if ext not in _IMAGE_TYPES:
        raise HTTPException(400, "Only PNG, JPEG and WebP files can be read")
    return _IMAGE_TYPES[ext]


def read_volume_image(ws, path: str) -> bytes:
    """Read a raster image the app's service principal can access (same reach as /browse)."""
    _image_media_type(path)
    try:
        return ws.files.download(path).contents.read()
    except Exception as e:
        raise HTTPException(404, f"Could not read {path}: {e}")


@router.get("/catalogs", response_model=list[CatalogOut], operation_id="listCatalogs")
def list_catalogs(ws: Dependencies.Client):
    try:
        return [
            CatalogOut(name=c.name, comment=c.comment)
            for c in ws.catalogs.list()
            if c.name and not c.name.startswith("__")
        ]
    except Exception as e:
        logger.exception("Failed to list catalogs")
        raise HTTPException(500, f"Failed to list catalogs: {e}")


@router.get(
    "/catalogs/{catalog_name}/schemas",
    response_model=list[SchemaOut],
    operation_id="listSchemas",
)
def list_schemas(catalog_name: str, ws: Dependencies.Client):
    try:
        return [
            SchemaOut(name=s.name, comment=s.comment)
            for s in ws.schemas.list(catalog_name=catalog_name)
            if s.name and not s.name.startswith("__")
        ]
    except Exception as e:
        logger.exception("Failed to list schemas")
        raise HTTPException(500, f"Failed to list schemas: {e}")


@router.get(
    "/catalogs/{catalog_name}/schemas/{schema_name}/volumes",
    response_model=list[VolumeOut],
    operation_id="listVolumes",
)
def list_volumes(catalog_name: str, schema_name: str, ws: Dependencies.Client):
    try:
        return [
            VolumeOut(
                name=v.name or "",
                full_name=v.full_name or "",
                volume_type=v.volume_type.value if v.volume_type else None,
            )
            for v in ws.volumes.list(catalog_name=catalog_name, schema_name=schema_name)
        ]
    except Exception as e:
        logger.exception("Failed to list volumes")
        raise HTTPException(500, f"Failed to list volumes: {e}")


@router.get("/browse", response_model=list[FileEntryOut], operation_id="browseVolumeFiles")
def browse_volume_files(path: str, ws: Dependencies.UserClient):
    if not path.startswith("/Volumes/"):
        raise HTTPException(400, "Path must start with /Volumes/")
    try:
        return [
            FileEntryOut(
                name=entry.name or "",
                path=entry.path or "",
                is_directory=entry.is_directory or False,
                file_size=entry.file_size,
            )
            for entry in ws.files.list_directory_contents(directory_path=path)
        ]
    except Exception as e:
        logger.exception("Failed to browse volume path: %s", path)
        raise HTTPException(500, f"Failed to browse volume: {e}")


@router.get("/file", operation_id="getVolumeImage")
def get_volume_image(path: str, ws: Dependencies.UserClient):
    """Serve a Volume image picked in the volume browser (Compose slot previews)."""
    return Response(content=read_volume_image(ws, path), media_type=_image_media_type(path))
