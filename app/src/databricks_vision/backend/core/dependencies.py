from __future__ import annotations

from typing import Annotated, TypeAlias

from psycopg_pool import ConnectionPool

from ._defaults import ConfigDependency, ClientDependency, UserWorkspaceClientDependency
from ._database import _DatabasePoolDependency
from ._headers import HeadersDependency
# Imported for its side effect: defining the class registers its lifespan hook with
# LifespanDependency._registry (VisionWorkspace + evaluator setup). Do not remove.
from ._image_gen_dep import _ImageGenDependency  # noqa: F401

DatabasePoolDependency: TypeAlias = Annotated[
    ConnectionPool, _DatabasePoolDependency.depends()
]


class Dependencies:
    """FastAPI dependency injection shorthand for route handler parameters."""

    Client: TypeAlias = ClientDependency
    """Databricks WorkspaceClient using app-level service principal credentials."""

    UserClient: TypeAlias = UserWorkspaceClientDependency
    """WorkspaceClient authenticated on behalf of the current user via OBO token."""

    Config: TypeAlias = ConfigDependency
    """Application configuration loaded from environment variables."""

    Headers: TypeAlias = HeadersDependency
    """Databricks Apps HTTP headers for the current request."""

    DB: TypeAlias = DatabasePoolDependency
    """Lakebase (PostgreSQL) connection pool (psycopg v3 ConnectionPool)."""
