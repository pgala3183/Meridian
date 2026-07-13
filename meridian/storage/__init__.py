"""Storage abstraction (local / GCS) and path safety helpers."""

from meridian.storage.base import ObjectStore, StorageBackendName, StoredObject, artifact_key
from meridian.storage.factory import StorageConfig, create_object_store
from meridian.storage.gcs_backend import GCSObjectStore
from meridian.storage.local_backend import LocalObjectStore
from meridian.storage.safe_path import (
    PathSandbox,
    PathSecurityError,
    contains_traversal,
    scratch_directory,
    scratch_file,
)

__all__ = [
    "GCSObjectStore",
    "LocalObjectStore",
    "ObjectStore",
    "PathSandbox",
    "PathSecurityError",
    "StorageBackendName",
    "StorageConfig",
    "StoredObject",
    "artifact_key",
    "contains_traversal",
    "create_object_store",
    "scratch_directory",
    "scratch_file",
]
