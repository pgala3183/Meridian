"""Local filesystem object store (dev / unit tests)."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from meridian.storage.base import ObjectStore, StoredObject
from meridian.storage.safe_path import PathSandbox


class LocalObjectStore(ObjectStore):
    """Sandbox-backed local blob store for development and tests."""

    def __init__(self, root: str | Path) -> None:
        self._sandbox = PathSandbox(root)

    @property
    def root(self) -> Path:
        return self._sandbox.root

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        path = self._sandbox.ensure_parent(key)
        path.write_bytes(data)
        return StoredObject(
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            uri=self.uri_for(key),
        )

    def put_file(
        self,
        key: str,
        fileobj: BinaryIO,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        return self.put_bytes(key, fileobj.read(), content_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        path = self._sandbox.resolve(key, must_exist=True)
        return path.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            path = self._sandbox.resolve(key, must_exist=False)
        except Exception:  # PathSecurityError and friends → miss
            return False
        return path.exists()

    def delete(self, key: str) -> None:
        try:
            path = self._sandbox.resolve(key, must_exist=False)
        except Exception:
            return
        if path.exists() and path.is_file():
            path.unlink()

    def uri_for(self, key: str) -> str:
        return self._sandbox.resolve(key, must_exist=False).as_uri()
