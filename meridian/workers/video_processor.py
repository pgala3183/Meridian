"""Cloud Run worker that consumes Pub/Sub push/pull video jobs."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response

load_dotenv()

from meridian.ingest.youtube import (  # noqa: E402
    demo_transcript,
    extract_youtube_id,
    fetch_youtube_transcript,
)
from meridian.jobs.firestore_store import FirestoreJobStore  # noqa: E402
from meridian.jobs.memory_store import InMemoryJobStore  # noqa: E402
from meridian.jobs.models import JobStage, JobStatus, JobStore, VideoJob  # noqa: E402
from meridian.jobs.queue import QueueMessage  # noqa: E402
from meridian.observability.context import clear_context, set_job_id, set_request_id  # noqa: E402
from meridian.observability.health import health_payload, readiness_payload  # noqa: E402
from meridian.observability.logging import configure_logging, get_logger  # noqa: E402
from meridian.observability.middleware import RequestContextMiddleware  # noqa: E402
from meridian.observability.tracing import (  # noqa: E402
    configure_telemetry,
    pipeline_stage_span,
    tracer,
)
from meridian.providers.types import Transcript  # noqa: E402
from meridian.storage.base import ObjectStore, StorageBackendName  # noqa: E402
from meridian.storage.factory import StorageConfig, create_object_store  # noqa: E402
from meridian.workers.indexing import build_context_tree, persist_index, tree_stats  # noqa: E402

logger = get_logger(__name__)


class VideoProcessor:
    """Ingest captions → semantic index → persist artifacts for grounded ask."""

    def __init__(self, store: JobStore, object_store: ObjectStore) -> None:
        self._store = store
        self._objects = object_store

    def process(self, message: QueueMessage) -> VideoJob:
        request_id = message.request_id or message.job_id
        set_request_id(request_id)
        set_job_id(message.job_id)

        job = self._store.get_job(message.job_id)
        if job is None:
            clear_context()
            raise KeyError(f"Unknown job_id {message.job_id}")

        if not job.request_id:
            job.request_id = request_id

        try:
            with tracer().start_as_current_span("worker.process_job") as root:
                root.set_attribute("meridian.job_id", job.job_id)
                root.set_attribute("meridian.video_id", job.video_id)
                root.set_attribute("meridian.request_id", request_id)
                logger.info(
                    "Processing job",
                    extra={"job_id": job.job_id, "request_id": request_id},
                )

                with pipeline_stage_span("transcribe", attributes=_attrs(job)):
                    job.status = JobStatus.RUNNING
                    job.stage = JobStage.TRANSCRIBE
                    job.progress = 0.15
                    job.updated_at = datetime.now(UTC)
                    self._store.update_job(job)

                    transcript = _resolve_transcript(job)
                    logger.info(
                        "Transcript ready",
                        extra={
                            "job_id": job.job_id,
                            "segments": len(transcript.segments),
                            "model": transcript.model,
                        },
                    )

                with pipeline_stage_span("embed", attributes=_attrs(job)):
                    job.stage = JobStage.EMBED
                    job.progress = 0.45
                    job.updated_at = datetime.now(UTC)
                    self._store.update_job(job)

                    tree = build_context_tree(job.video_id, transcript)
                    stats = tree_stats(tree)
                    logger.info(
                        "Index built",
                        extra={"job_id": job.job_id, **{k: stats[k] for k in ("chunk_count",)}},
                    )

                with pipeline_stage_span("index", attributes=_attrs(job)):
                    job.stage = JobStage.INDEX
                    job.progress = 0.8
                    job.updated_at = datetime.now(UTC)
                    self._store.update_job(job)

                    uris = persist_index(
                        self._objects,
                        video_id=job.video_id,
                        transcript=transcript,
                        tree=tree,
                    )
                    job.artifact_uris["transcript"] = uris["transcript"]
                    job.artifact_uris["context_tree"] = uris["context_tree"]
                    job.extra["transcript_key"] = uris["transcript_key"]
                    job.extra["context_tree_key"] = uris["context_tree_key"]
                    job.extra["chunk_count"] = stats["chunk_count"]
                    job.extra["transcript_model"] = transcript.model

                with pipeline_stage_span("complete", attributes=_attrs(job)):
                    job.stage = JobStage.COMPLETE
                    job.status = JobStatus.SUCCEEDED
                    job.progress = 1.0
                    job.completed_at = datetime.now(UTC)
                    job.updated_at = job.completed_at
                    return self._store.update_job(job)
        except Exception as exc:
            logger.exception("Job %s failed", message.job_id)
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.updated_at = datetime.now(UTC)
            self._store.update_job(job)
            raise
        finally:
            clear_context()


def _resolve_transcript(job: VideoJob) -> Transcript:
    yt_id = extract_youtube_id(job.source_uri) or extract_youtube_id(job.video_id)
    if yt_id:
        return fetch_youtube_transcript(yt_id)
    return demo_transcript(job.video_id)


def _attrs(job: VideoJob) -> dict[str, str]:
    return {
        "meridian.job_id": job.job_id,
        "meridian.video_id": job.video_id,
        "meridian.request_id": job.request_id or "",
    }


def create_worker_app(
    *,
    store: JobStore,
    object_store: ObjectStore,
) -> FastAPI:
    """Build the Cloud Run worker HTTP app (Pub/Sub push endpoint)."""
    configure_logging(service="meridian-worker")
    configure_telemetry(service_name="meridian-worker")

    processor = VideoProcessor(store, object_store)
    app = FastAPI(title="Meridian Video Worker", version="0.1.0")
    app.state.processor = processor
    app.state.job_store = store
    app.state.object_store = object_store
    app.add_middleware(RequestContextMiddleware, service="worker")

    @app.get("/health")
    def health() -> dict[str, str]:
        return health_payload(role="worker")

    @app.get("/ready")
    def ready(response: Response) -> dict[str, Any]:
        body, status = readiness_payload(
            role="worker",
            checks={
                "job_store": store is not None,
                "object_store": object_store is not None,
            },
        )
        response.status_code = status
        return body

    @app.post("/pubsub/push")
    async def pubsub_push(request: Request) -> dict[str, str]:
        """Pub/Sub push subscription handler."""
        body = await request.json()
        try:
            message = _parse_pubsub_envelope(body)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid Pub/Sub envelope: {exc}") from exc
        try:
            processor.process(message)
        except KeyError as exc:
            logger.warning("%s", exc)
            return {"status": "ignored"}
        return {"status": "ok"}

    return app


def _parse_pubsub_envelope(body: dict[str, Any]) -> QueueMessage:
    encoded = body["message"]["data"]
    raw = base64.b64decode(encoded)
    message = QueueMessage.from_bytes(raw)
    attrs = body.get("message", {}).get("attributes") or {}
    attr_rid = attrs.get("request_id")
    if attr_rid and not message.request_id:
        return QueueMessage(
            job_id=message.job_id,
            video_id=message.video_id,
            user_id=message.user_id,
            stage_hint=message.stage_hint,
            request_id=str(attr_rid),
        )
    return message


def _default_store() -> JobStore:
    if os.getenv("MERIDIAN_JOB_STORE", "memory").lower() == "firestore":
        return FirestoreJobStore(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
    return InMemoryJobStore()


def _default_object_store() -> ObjectStore:
    backend = os.getenv("MERIDIAN_STORAGE_BACKEND", "local").lower()
    name = StorageBackendName.GCS if backend == "gcs" else StorageBackendName.LOCAL
    return create_object_store(
        StorageConfig(
            backend=name,
            local_root=os.getenv("MERIDIAN_LOCAL_STORAGE", ".meridian-data/worker-objects"),
            gcs_bucket=os.getenv("MERIDIAN_GCS_BUCKET"),
            gcs_prefix=os.getenv("MERIDIAN_GCS_PREFIX", "meridian"),
        )
    )


app = create_worker_app(store=_default_store(), object_store=_default_object_store())
