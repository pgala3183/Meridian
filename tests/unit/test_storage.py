"""Unit tests for object storage backends."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from meridian.storage.base import artifact_key
from meridian.storage.factory import StorageBackendName, StorageConfig, create_object_store
from meridian.storage.gcs_backend import GCSObjectStore
from meridian.storage.local_backend import LocalObjectStore


def test_local_object_store_roundtrip(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    key = artifact_key("vid-1", "transcripts", "full.json")
    stored = store.put_bytes(key, b'{"ok":true}', content_type="application/json")
    assert stored.size_bytes > 0
    assert store.exists(key)
    assert store.get_bytes(key) == b'{"ok":true}'
    store.delete(key)
    assert not store.exists(key)


def test_create_object_store_local(tmp_path: Path) -> None:
    store = create_object_store(
        StorageConfig(backend=StorageBackendName.LOCAL, local_root=str(tmp_path / "obj"))
    )
    assert isinstance(store, LocalObjectStore)
    store.put_bytes("a/b.txt", b"x")
    assert store.get_bytes("a/b.txt") == b"x"


def test_gcs_object_store_with_fake_client() -> None:
    class _Blob:
        def __init__(self) -> None:
            self.data: bytes | None = None
            self.content_type: str | None = None

        def upload_from_string(self, data: bytes, content_type: str | None = None) -> None:
            self.data = data
            self.content_type = content_type

        def exists(self) -> bool:
            return self.data is not None

        def download_as_bytes(self) -> bytes:
            assert self.data is not None
            return self.data

        def delete(self) -> None:
            self.data = None

    class _Bucket:
        def __init__(self) -> None:
            self.blobs: dict[str, _Blob] = {}

        def blob(self, name: str) -> _Blob:
            if name not in self.blobs:
                self.blobs[name] = _Blob()
            return self.blobs[name]

    class _Client:
        def __init__(self) -> None:
            self.bucket_obj = _Bucket()

        def bucket(self, _name: str) -> _Bucket:
            return self.bucket_obj

    client: Any = _Client()
    store = GCSObjectStore("demo-bucket", client=client, prefix="meridian")
    key = "videos/v1/context/tree.json"
    store.put_bytes(key, b"{}", content_type="application/json")
    assert store.exists(key)
    assert store.get_bytes(key) == b"{}"
    assert store.uri_for(key) == "gs://demo-bucket/meridian/videos/v1/context/tree.json"
    store.delete(key)
    assert not store.exists(key)


def test_gcs_requires_bucket() -> None:
    with pytest.raises(ValueError, match="bucket"):
        GCSObjectStore("")
