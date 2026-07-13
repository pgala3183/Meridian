"""In-memory job store for unit tests / local smoke runs."""

from __future__ import annotations

import threading
from copy import deepcopy

from meridian.jobs.models import CacheIndexEntry, JobStore, VideoJob


class InMemoryJobStore(JobStore):
    """Thread-safe dict-backed store (never used as production state)."""

    def __init__(self) -> None:
        self._jobs: dict[str, VideoJob] = {}
        self._cache: dict[str, CacheIndexEntry] = {}
        self._lock = threading.RLock()

    def create_job(self, job: VideoJob) -> VideoJob:
        with self._lock:
            if job.job_id in self._jobs:
                raise ValueError(f"Job already exists: {job.job_id}")
            stored = job.model_copy(deep=True)
            self._jobs[job.job_id] = stored
            return deepcopy(stored)

    def get_job(self, job_id: str) -> VideoJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def update_job(self, job: VideoJob) -> VideoJob:
        with self._lock:
            if job.job_id not in self._jobs:
                raise KeyError(job.job_id)
            stored = job.model_copy(deep=True)
            self._jobs[job.job_id] = stored
            return deepcopy(stored)

    def put_cache_index(self, entry: CacheIndexEntry) -> CacheIndexEntry:
        with self._lock:
            stored = entry.model_copy(deep=True)
            self._cache[entry.cache_key] = stored
            return deepcopy(stored)

    def get_cache_index(self, cache_key: str) -> CacheIndexEntry | None:
        with self._lock:
            entry = self._cache.get(cache_key)
            return deepcopy(entry) if entry else None
