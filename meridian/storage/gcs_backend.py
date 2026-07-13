"""Google Cloud Storage object store."""

from __future__ import annotations

from typing import Any, BinaryIO

from meridian.storage.base import ObjectStore, StoredObject


class GCSObjectStore(ObjectStore):
    """GCS-backed blob store for production artifacts.

    Client injection keeps unit tests free of real GCP credentials.
    """

    def __init__(
        self,
        bucket_name: str,
        *,
        client: Any | None = None,
        prefix: str = "",
    ) -> None:
        if not bucket_name:
            raise ValueError("GCSObjectStore requires a bucket_name")
        self.bucket_name = bucket_name
        self._prefix = prefix.strip("/")
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import storage as gcs_storage  # type: ignore[attr-defined]

            self._client = gcs_storage.Client()
        return self._client

    def _blob(self, key: str) -> Any:
        full_key = f"{self._prefix}/{key}" if self._prefix else key
        bucket = self._get_client().bucket(self.bucket_name)
        return bucket.blob(full_key)

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        blob = self._blob(key)
        blob.upload_from_string(data, content_type=content_type)
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
        data = fileobj.read()
        return self.put_bytes(key, data, content_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        blob = self._blob(key)
        if not blob.exists():
            raise FileNotFoundError(key)
        raw = blob.download_as_bytes()
        return bytes(raw)

    def exists(self, key: str) -> bool:
        return bool(self._blob(key).exists())

    def delete(self, key: str) -> None:
        blob = self._blob(key)
        if blob.exists():
            blob.delete()

    def uri_for(self, key: str) -> str:
        full_key = f"{self._prefix}/{key}" if self._prefix else key
        return f"gs://{self.bucket_name}/{full_key}"
