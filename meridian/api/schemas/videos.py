"""API request / response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from meridian.jobs.models import JobStage, JobStatus


class EnqueueVideoRequest(BaseModel):
    """POST /videos body."""

    video_id: str = Field(min_length=1, max_length=128)
    source_uri: str | None = Field(
        default=None,
        description="Optional https remote URI or gs:// object URI",
    )
    webhook_url: HttpUrl | None = None
    user_id: str = Field(default="anonymous", min_length=1, max_length=128)


class EnqueueVideoResponse(BaseModel):
    """Immediate acknowledgment — processing continues asynchronously."""

    job_id: str
    status: JobStatus = JobStatus.QUEUED
    poll_url: str
    events_url: str


class JobStatusResponse(BaseModel):
    """GET /videos/{job_id}/status payload."""

    job_id: str
    video_id: str
    status: JobStatus
    stage: JobStage
    progress: float
    error_message: str | None = None
    artifact_uris: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
