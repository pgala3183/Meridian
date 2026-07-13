"""Video job API routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from meridian.api.rate_limit import RateLimitExceeded, TokenBucketRateLimiter
from meridian.api.schemas.videos import (
    EnqueueVideoRequest,
    EnqueueVideoResponse,
    JobStatusResponse,
)
from meridian.jobs.models import JobStatus, VideoJob
from meridian.jobs.queue import JobQueue, QueueMessage

router = APIRouter(prefix="/videos", tags=["videos"])


def get_job_store(request: Request) -> Any:
    return request.app.state.job_store


def get_job_queue(request: Request) -> JobQueue:
    return request.app.state.job_queue  # type: ignore[no-any-return]


def get_rate_limiter(request: Request) -> TokenBucketRateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


StoreDep = Annotated[Any, Depends(get_job_store)]
QueueDep = Annotated[JobQueue, Depends(get_job_queue)]
LimiterDep = Annotated[TokenBucketRateLimiter, Depends(get_rate_limiter)]
ApiKeyDep = Annotated[str | None, Header(alias="X-API-Key")]


def _identity(*, x_api_key: str | None, body_user_id: str | None) -> str:
    if x_api_key:
        return f"key:{x_api_key}"
    if body_user_id:
        return f"user:{body_user_id}"
    return "user:anonymous"


@router.post("", response_model=EnqueueVideoResponse, status_code=202)
def enqueue_video(
    payload: EnqueueVideoRequest,
    request: Request,
    store: StoreDep,
    queue: QueueDep,
    limiter: LimiterDep,
    x_api_key: ApiKeyDep = None,
) -> EnqueueVideoResponse:
    """Enqueue async processing; returns ``job_id`` immediately (HTTP 202)."""
    identity = _identity(x_api_key=x_api_key, body_user_id=payload.user_id)
    try:
        limiter.allow(identity)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(int(exc.retry_after_seconds) + 1)},
        ) from exc

    job = VideoJob(
        user_id=payload.user_id,
        video_id=payload.video_id,
        source_uri=payload.source_uri,
        webhook_url=str(payload.webhook_url) if payload.webhook_url else None,
        status=JobStatus.QUEUED,
    )
    store.create_job(job)
    queue.enqueue(QueueMessage.from_job(job))
    base = str(request.base_url).rstrip("/")
    return EnqueueVideoResponse(
        job_id=job.job_id,
        status=job.status,
        poll_url=f"{base}/videos/{job.job_id}/status",
        events_url=f"{base}/videos/{job.job_id}/events",
    )


@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: str, store: StoreDep) -> JobStatusResponse:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        job_id=job.job_id,
        video_id=job.video_id,
        status=job.status,
        stage=job.stage,
        progress=job.progress,
        error_message=job.error_message,
        artifact_uris=job.artifact_uris,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


@router.get("/{job_id}/events")
async def job_events(job_id: str, store: StoreDep) -> StreamingResponse:
    """Server-Sent Events stream of job status until terminal state."""

    async def event_generator() -> AsyncIterator[str]:
        last_payload = ""
        while True:
            job = store.get_job(job_id)
            if job is None:
                yield _sse({"error": "not_found"})
                return
            payload = JobStatusResponse(
                job_id=job.job_id,
                video_id=job.video_id,
                status=job.status,
                stage=job.stage,
                progress=job.progress,
                error_message=job.error_message,
                artifact_uris=job.artifact_uris,
                created_at=job.created_at,
                updated_at=job.updated_at,
                completed_at=job.completed_at,
            ).model_dump_json()
            if payload != last_payload:
                yield _sse(json.loads(payload))
                last_payload = payload
            if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, default=str)}\n\n"


def mark_job_updated(job: VideoJob) -> VideoJob:
    job.updated_at = datetime.now(UTC)
    return job
