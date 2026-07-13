"""Job / video processing state models and store abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(StrEnum):
    INGEST = "ingest"
    TRANSCRIBE = "transcribe"
    EMBED = "embed"
    INDEX = "index"
    COMPLETE = "complete"


class VideoJob(BaseModel):
    """Durable record for an async video-processing job."""

    job_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    video_id: str
    request_id: str | None = Field(
        default=None,
        description="Correlation ID from the enqueueing HTTP request",
    )
    source_uri: str | None = None
    status: JobStatus = JobStatus.QUEUED
    stage: JobStage = JobStage.INGEST
    error_message: str | None = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    artifact_uris: dict[str, str] = Field(default_factory=dict)
    cache_key: str | None = None
    webhook_url: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CacheIndexEntry(BaseModel):
    """Firestore index pointing at a cached context tree in object storage."""

    cache_key: str
    video_id: str
    object_uri: str
    content_hash: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None


class JobStore(ABC):
    """Persistence for job records and cache-index metadata."""

    @abstractmethod
    def create_job(self, job: VideoJob) -> VideoJob:
        """Insert a new job document."""

    @abstractmethod
    def get_job(self, job_id: str) -> VideoJob | None:
        """Fetch a job by id."""

    @abstractmethod
    def update_job(self, job: VideoJob) -> VideoJob:
        """Overwrite / merge a job document."""

    @abstractmethod
    def put_cache_index(self, entry: CacheIndexEntry) -> CacheIndexEntry:
        """Upsert cache index metadata."""

    @abstractmethod
    def get_cache_index(self, cache_key: str) -> CacheIndexEntry | None:
        """Lookup cache index by content-hash key."""
