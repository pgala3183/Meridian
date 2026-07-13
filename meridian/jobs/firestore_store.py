"""Firestore-backed job and cache-index store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from meridian.jobs.models import CacheIndexEntry, JobStore, VideoJob

_JOBS = "video_jobs"
_CACHE = "cache_index"


class FirestoreJobStore(JobStore):
    """Production state store using Cloud Firestore.

    Job documents are keyed by ``job_id``; cache index by ``cache_key``.
    Clients are injectable for tests.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        project: str | None = None,
        database: str = "(default)",
    ) -> None:
        self._client = client
        self._project = project
        self._database = database

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import firestore

            kwargs: dict[str, Any] = {}
            if self._project:
                kwargs["project"] = self._project
            if self._database != "(default)":
                kwargs["database"] = self._database
            self._client = firestore.Client(**kwargs)
        return self._client

    def create_job(self, job: VideoJob) -> VideoJob:
        client = self._get_client()
        ref = client.collection(_JOBS).document(job.job_id)
        if ref.get().exists:
            raise ValueError(f"Job already exists: {job.job_id}")
        ref.set(job.model_dump(mode="json"))
        return job

    def get_job(self, job_id: str) -> VideoJob | None:
        snap = self._get_client().collection(_JOBS).document(job_id).get()
        if not snap.exists:
            return None
        return VideoJob.model_validate(snap.to_dict())

    def update_job(self, job: VideoJob) -> VideoJob:
        job.updated_at = datetime.now(UTC)
        ref = self._get_client().collection(_JOBS).document(job.job_id)
        if not ref.get().exists:
            raise KeyError(job.job_id)
        ref.set(job.model_dump(mode="json"), merge=True)
        return job

    def put_cache_index(self, entry: CacheIndexEntry) -> CacheIndexEntry:
        self._get_client().collection(_CACHE).document(entry.cache_key).set(
            entry.model_dump(mode="json"),
            merge=True,
        )
        return entry

    def get_cache_index(self, cache_key: str) -> CacheIndexEntry | None:
        snap = self._get_client().collection(_CACHE).document(cache_key).get()
        if not snap.exists:
            return None
        return CacheIndexEntry.model_validate(snap.to_dict())
