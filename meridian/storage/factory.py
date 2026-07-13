"""Storage factory — dependency-injected backend selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meridian.storage.base import ObjectStore, StorageBackendName
from meridian.storage.gcs_backend import GCSObjectStore
from meridian.storage.local_backend import LocalObjectStore


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """Runtime storage selection."""

    backend: StorageBackendName = StorageBackendName.LOCAL
    local_root: str = ".meridian-data/objects"
    gcs_bucket: str | None = None
    gcs_prefix: str = "meridian"


def create_object_store(
    config: StorageConfig | None = None,
    *,
    gcs_client: Any | None = None,
) -> ObjectStore:
    """Build an ``ObjectStore`` from config (local by default for tests/dev)."""
    cfg = config or StorageConfig()
    if cfg.backend is StorageBackendName.LOCAL:
        Path(cfg.local_root).mkdir(parents=True, exist_ok=True)
        return LocalObjectStore(cfg.local_root)
    if cfg.backend is StorageBackendName.GCS:
        if not cfg.gcs_bucket:
            raise ValueError("StorageConfig.gcs_bucket is required for GCS backend")
        return GCSObjectStore(
            cfg.gcs_bucket,
            client=gcs_client,
            prefix=cfg.gcs_prefix,
        )
    raise ValueError(f"Unknown storage backend: {cfg.backend}")
