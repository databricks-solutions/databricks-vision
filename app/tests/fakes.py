"""Minimal stand-ins for the Databricks SDK surface the routes touch in tests."""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from typing import Any

from databricks.sdk.service.iam import User


class FakeFiles:
    """In-memory UC Volume Files API (upload / download / delete)."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def upload(self, file_path: str, contents: Any, overwrite: bool = False) -> None:
        data = contents.read() if hasattr(contents, "read") else bytes(contents)
        if file_path in self.store and not overwrite:
            raise FileExistsError(file_path)
        self.store[file_path] = data

    def download(self, file_path: str) -> SimpleNamespace:
        if file_path not in self.store:
            raise FileNotFoundError(file_path)
        return SimpleNamespace(contents=BytesIO(self.store[file_path]))

    def delete(self, file_path: str) -> None:
        self.deleted.append(file_path)
        self.store.pop(file_path, None)


class FakeConfig:
    host = "https://example.cloud.databricks.com"
    client_id = "00000000-0000-0000-0000-000000000000"

    def authenticate(self, headers: dict | None = None) -> dict:
        # No Authorization header: code paths that call out over HTTP short-circuit.
        return {}


class FakeCurrentUser:
    def me(self) -> User:
        return User(user_name="tester@example.com", display_name="Test User")


class FakeWorkspaceClient:
    def __init__(self) -> None:
        self.files = FakeFiles()
        self.config = FakeConfig()
        self.current_user = FakeCurrentUser()
