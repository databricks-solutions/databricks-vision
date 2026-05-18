"""ImageGen / ImageAnalyzer dependency injection.

The app holds one shared `VisionWorkspace` (built from the SP-bound WorkspaceClient and the
existing Lakebase pool). Per-request, we mint an OBO-authenticated `AsyncOpenAI` client via
`vw.openai_for_token(...)` and construct a fresh `ImageGen` / `ImageAnalyzer` on top, so user
identity flows through to model-serving while the pool + SigLIP endpoint stay SP-bound.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from image_gen import ImageAnalyzer, ImageGen, VisionWorkspace

from ._base import LifespanDependency
from ._config import logger


def _get_obo_token(request: Request) -> str | None:
    """Extract the user's OBO token from the X-Forwarded-Access-Token header."""
    return request.headers.get("X-Forwarded-Access-Token")


def get_sp_token(request: Request) -> str:
    """Mint a fresh SP token from the SDK's auth provider.

    SP/OAuth tokens have a ~1-hour TTL. We deliberately do NOT cache the value at
    app startup — every Phase-2 background task / OBO-fallback call extracts a new
    one here. The SDK's `Config.authenticate()` already does its own internal
    refresh-with-cache, so calling this on every request is cheap.
    """
    ws = request.app.state.workspace_client
    return _extract_sp_token(ws) or ""


def _get_user_token(request: Request) -> str:
    """Token for OpenAI / Responses calls — returns the service principal token.

    Mirrors the file-ops policy in core/_defaults._get_user_ws. To restore
    per-user OBO, swap to:
        return _get_obo_token(request) or get_sp_token(request)
    VisionWorkspace.openai_for_token accepts whatever token is handed in.
    """
    return get_sp_token(request)


def get_workspace(request: Request) -> VisionWorkspace:
    return request.app.state.vision_workspace


def get_image_gen(request: Request) -> ImageGen:
    """Per-request ImageGen — uses the caller's OBO token for OpenAI / Responses calls."""
    vw: VisionWorkspace = request.app.state.vision_workspace
    cfg = request.app.state.config
    oai = vw.openai_for_token(_get_user_token(request))
    return ImageGen(
        workspace=vw,
        output_root=cfg.output_volume,
        reasoning_model=cfg.model_name,
        image_model=cfg.image_model,
        openai_client=oai,
    )


def get_image_analyzer(request: Request) -> ImageAnalyzer:
    """Per-request ImageAnalyzer — uses the caller's OBO token."""
    vw: VisionWorkspace = request.app.state.vision_workspace
    cfg = request.app.state.config
    oai = vw.openai_for_token(_get_user_token(request))
    return ImageAnalyzer(workspace=vw, model=cfg.model_name, openai_client=oai)


def _extract_sp_token(ws) -> str | None:
    try:
        auth_headers = ws.config.authenticate()
        auth_value = auth_headers.get("Authorization", "") if isinstance(auth_headers, dict) else ""
        if auth_value.startswith("Bearer "):
            return auth_value[len("Bearer "):]
    except Exception as exc:
        logger.warning("Could not get SP auth token: %s", exc)
    return None


class _ImageGenDependency(LifespanDependency):
    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        ws = app.state.workspace_client
        cfg = app.state.config

        # The Lakebase pool was opened by _DatabasePoolDependency earlier in lifespan order.
        pool = getattr(app.state, "db_pool", None)

        vw = VisionWorkspace(
            client=ws,
            pool=pool,
            embedding_endpoint=getattr(cfg, "embedding_endpoint", "siglip-so400m-embeddings"),
        )
        app.state.vision_workspace = vw
        # Note: we deliberately do NOT cache an SP token at startup any more — see
        # get_sp_token(). Tokens have ~1h TTL; callers mint a fresh one each time.

        logger.info("VisionWorkspace initialized (SP-bound; pool=%s)", pool is not None)
        yield

    @staticmethod
    def __call__(request: Request) -> ImageGen:
        # Route Annotated[ImageGen, Depends(...)] sites through the per-request constructor.
        return get_image_gen(request)
