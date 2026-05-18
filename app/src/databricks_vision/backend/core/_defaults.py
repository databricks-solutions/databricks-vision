from __future__ import annotations
from typing import Annotated, AsyncGenerator, TypeAlias
from contextlib import asynccontextmanager

from databricks.sdk import WorkspaceClient
from fastapi import Depends, FastAPI, Request

from ._base import LifespanDependency
from ._config import AppConfig, logger
from ._headers import HeadersDependency


class _ConfigDependency(LifespanDependency):
    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.config = AppConfig()
        logger.info(f"Starting app with configuration:\n{app.state.config}")
        yield

    @staticmethod
    def __call__(request: Request) -> AppConfig:
        return request.app.state.config


class _WorkspaceClientDependency(LifespanDependency):
    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.workspace_client = WorkspaceClient()
        yield

    @staticmethod
    def __call__(request: Request) -> WorkspaceClient:
        return request.app.state.workspace_client


def _get_user_ws(
    request: Request,
    headers: HeadersDependency,
) -> WorkspaceClient:
    """Per-request WorkspaceClient for file / SDK operations — always SP-bound.

    We deliberately ignore the OBO token here. Databricks Apps' user-facing scope
    `files.files` ("Manage your files and directories") doesn't actually map to the
    `files` scope the Files API requires, so OBO-bound `ws.files.download` returns
    "Invalid scope, required scopes: files" even when the user has the access
    granted. Routing file ops through the SP (which has the necessary Volume
    grants applied at deploy time) is also the right architecture for the
    shared-asset use case — every co-worker sees the same gallery regardless of
    their UC privileges.

    User attribution is still available via the X-Forwarded-Email header (set by
    the Apps proxy) when a route needs to stamp `created_by` etc. Per-user
    compute attribution still works because the OpenAI/Responses path uses
    `vw.openai_for_token(<obo_token>)` directly, not this helper.
    """
    return request.app.state.workspace_client


ConfigDependency: TypeAlias = Annotated[AppConfig, _ConfigDependency.depends()]

ClientDependency: TypeAlias = Annotated[
    WorkspaceClient, _WorkspaceClientDependency.depends()
]

UserWorkspaceClientDependency: TypeAlias = Annotated[
    WorkspaceClient, Depends(_get_user_ws)
]
