from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import APIRouter, FastAPI

from ..._metadata import api_prefix, app_name, dist_dir
from ._base import LifespanDependency
from ._config import logger


@asynccontextmanager
async def _chain_dep_lifespans(
    deps: list[LifespanDependency],
    app: FastAPI,
) -> AsyncIterator[None]:
    if not deps:
        yield
        return

    head, *tail = deps

    async with head.lifespan(app):
        async with _chain_dep_lifespans(tail, app):
            yield


def create_app(
    *,
    routers: list[APIRouter] | None = None,
) -> FastAPI:
    all_deps: list[LifespanDependency] = []
    for dep in LifespanDependency._registry:
        try:
            all_deps.append(dep())
        except Exception as e:
            logger.error(f"Failed to instantiate dependency {dep.__name__}: {e}")
            raise e

    @asynccontextmanager
    async def _composed_lifespan(app: FastAPI):
        async with _chain_dep_lifespans(all_deps, app):
            yield

    app = FastAPI(title=app_name, lifespan=_composed_lifespan)

    api_router: APIRouter = create_router()
    for dep in all_deps:
        for r in dep.get_routers():
            api_router.include_router(r)
    app.include_router(api_router)

    for router in routers or []:
        if router is not api_router:
            app.include_router(router)

    if dist_dir.exists():
        from ._static import CachedStaticFiles, add_not_found_handler

        app.mount("/", CachedStaticFiles(directory=dist_dir, html=True))
        add_not_found_handler(app)

    return app


@lru_cache(maxsize=1)
def create_router() -> APIRouter:
    return APIRouter(prefix=api_prefix)
