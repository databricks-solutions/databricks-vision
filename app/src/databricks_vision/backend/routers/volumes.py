import logging

from fastapi import APIRouter, HTTPException

from ..core import Dependencies
from ..models import CatalogOut, FileEntryOut, SchemaOut, VolumeOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/volumes", tags=["volumes"])


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
