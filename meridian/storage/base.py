"""Object-storage abstraction for Meridian artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO


class StorageBackendName(StrEnum):
    LOCAL = "local"
    GCS = "gcs"


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Metadata for an object written to storage."""

    key: str
    size_bytes: int
    content_type: str | None = None
    uri: str | None = None


class ObjectStore(ABC):
    """Provider-agnostic blob store for transcripts, keyframes, and caches."""

    @abstractmethod
    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        """Write bytes to ``key``."""

    @abstractmethod
    def put_file(
        self,
        key: str,
        fileobj: BinaryIO,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        """Stream a file-like object to ``key``."""

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        """Read object bytes or raise ``FileNotFoundError``."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if ``key`` exists."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete ``key`` if present (idempotent)."""

    @abstractmethod
    def uri_for(self, key: str) -> str:
        """Return a backend-specific URI for ``key`` (not necessarily signed)."""


def artifact_key(video_id: str, kind: str, name: str) -> str:
    """Stable object key layout: ``videos/{id}/{kind}/{name}``."""
    safe_kind = kind.strip("/").replace("..", "")
    safe_name = name.strip("/").replace("..", "")
    return f"videos/{video_id}/{safe_kind}/{safe_name}"
