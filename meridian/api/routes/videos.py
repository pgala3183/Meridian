"""Video job API routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from meridian.api.rate_limit import RateLimitExceeded, TokenBucketRateLimiter
from meridian.api.schemas.ask import AskRequest, AskResponse, CitationOut
from meridian.api.schemas.videos import (
    EnqueueVideoRequest,
    EnqueueVideoResponse,
    JobStatusResponse,
)
from meridian.jobs.models import JobStatus, JobStore, VideoJob
from meridian.jobs.queue import InMemoryJobQueue, JobQueue, QueueMessage
from meridian.storage.base import ObjectStore
from meridian.workers.video_processor import VideoProcessor

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
    background_tasks: BackgroundTasks,
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
        request_id=getattr(request.state, "request_id", None),
    )
    store.create_job(job)
    queue.enqueue(QueueMessage.from_job(job))

    # Local/demo: in-memory queue has no Pub/Sub worker — process in-process.
    if isinstance(queue, InMemoryJobQueue):
        object_store: ObjectStore = request.app.state.object_store
        background_tasks.add_task(_run_local_job, store, object_store, job.job_id)

    base = str(request.base_url).rstrip("/")
    return EnqueueVideoResponse(
        job_id=job.job_id,
        status=job.status,
        poll_url=f"{base}/videos/{job.job_id}/status",
        events_url=f"{base}/videos/{job.job_id}/events",
    )


def _run_local_job(store: JobStore, object_store: ObjectStore, job_id: str) -> None:
    job = store.get_job(job_id)
    if job is None:
        return
    VideoProcessor(store, object_store).process(QueueMessage.from_job(job))


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


@router.post("/{job_id}/ask", response_model=AskResponse)
def ask_video(
    job_id: str,
    payload: AskRequest,
    store: StoreDep,
    limiter: LimiterDep,
    x_api_key: ApiKeyDep = None,
) -> AskResponse:
    """Grounded Q&A against a completed job (demo-friendly cited answers)."""
    identity = _identity(x_api_key=x_api_key, body_user_id=None)
    try:
        limiter.allow(identity, cost=2.0)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(int(exc.retry_after_seconds) + 1)},
        ) from exc

    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status is not JobStatus.SUCCEEDED:
        raise HTTPException(
            status_code=409,
            detail=f"Job is {job.status.value}; wait until processing succeeds",
        )

    answer, citations = _demo_grounded_answer(job, payload.question)
    return AskResponse(
        answer=answer,
        citations=citations,
        job_id=job.job_id,
        model="meridian-demo",
    )


def _demo_grounded_answer(
    job: VideoJob,
    question: str,
) -> tuple[str, list[CitationOut]]:
    """Produce a cited answer for the web demo without requiring live LLM calls.

    Uses question heuristics + job metadata so the UI can demonstrate seekable
    citations. Production will swap this for the hierarchical pipeline ask path.
    """
    q = question.lower()
    # Stagger demo timestamps so different questions seek different moments.
    if any(token in q for token in ("cache", "memory", "latency")):
        start, end = 12.0, 28.0
        excerpt = (
            "A CPU cache stores frequently used data closer to the processor "
            "to reduce average memory latency."
        )
        answer = (
            "The talk explains that CPU caches keep hot data near the processor "
            "so average memory latency drops."
        )
    elif any(token in q for token in ("miss", "fetch")):
        start, end = 52.0, 62.0
        excerpt = "On a cache miss the system fetches the block from slower main memory."
        answer = (
            "On a cache miss, the system fetches the needed block from slower "
            "main memory into the cache."
        )
    elif any(token in q for token in ("citation", "timestamp", "seek", "click")):
        start, end = 24.0, 32.0
        excerpt = "Clicking a citation seeks the player to that timestamp automatically."
        answer = (
            "In the product flow, clicking a citation seeks the embedded player "
            "to the cited timestamp."
        )
    elif any(token in q for token in ("eval", "offline", "a/b", "shadow", "ship")):
        start, end = 18.0, 38.0
        excerpt = (
            "First we run offline evals on a labeled set, then shadow traffic, "
            "then a small A/B test."
        )
        answer = (
            "The founder describes a validation ladder: offline evals, then "
            "shadow traffic, then a gated A/B test before launch."
        )
    else:
        start, end = 6.0, 18.0
        excerpt = f"Processing for video {job.video_id} completed successfully."
        answer = (
            f"Based on the indexed content for `{job.video_id}`, Meridian retrieved "
            "grounded segments for your question. Try asking about caching, "
            "citations, or how features are validated before launch."
        )

    citation = CitationOut(
        start_time=start,
        end_time=end,
        transcript_excerpt=excerpt,
        chunk_id="chunk-0000",
    )
    return f"{answer} [{citation.chunk_id} | {start:.0f}s-{end:.0f}s]", [citation]


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, default=str)}\n\n"


def mark_job_updated(job: VideoJob) -> VideoJob:
    job.updated_at = datetime.now(UTC)
    return job
