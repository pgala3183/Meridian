"""Cloud Run worker that consumes Pub/Sub push/pull video jobs."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from meridian.jobs.firestore_store import FirestoreJobStore
from meridian.jobs.memory_store import InMemoryJobStore
from meridian.jobs.models import JobStage, JobStatus, JobStore, VideoJob
from meridian.jobs.queue import QueueMessage
from meridian.storage.base import ObjectStore, StorageBackendName, artifact_key
from meridian.storage.factory import StorageConfig, create_object_store

logger = logging.getLogger(__name__)


class VideoProcessor:
    """Processes a single queued video job end-to-end (pipeline stages later).

    For now this advances job state, writes placeholder artifacts to object
    storage, and updates Firestore/memory job records — enough to exercise the
    async control plane without blocking the API.
    """

    def __init__(self, store: JobStore, object_store: ObjectStore) -> None:
        self._store = store
        self._objects = object_store

    def process(self, message: QueueMessage) -> VideoJob:
        job = self._store.get_job(message.job_id)
        if job is None:
            raise KeyError(f"Unknown job_id {message.job_id}")

        try:
            job.status = JobStatus.RUNNING
            job.stage = JobStage.TRANSCRIBE
            job.progress = 0.2
            job.updated_at = datetime.now(UTC)
            self._store.update_job(job)

            transcript_key = artifact_key(job.video_id, "transcripts", "full.json")
            transcript_blob = json.dumps(
                {
                    "video_id": job.video_id,
                    "job_id": job.job_id,
                    "note": "placeholder transcript — pipeline wiring lands next",
                }
            ).encode("utf-8")
            stored = self._objects.put_bytes(
                transcript_key,
                transcript_blob,
                content_type="application/json",
            )
            job.artifact_uris["transcript"] = stored.uri or self._objects.uri_for(transcript_key)

            job.stage = JobStage.EMBED
            job.progress = 0.6
            job.updated_at = datetime.now(UTC)
            self._store.update_job(job)

            tree_key = artifact_key(job.video_id, "context", "tree.json")
            tree_blob = json.dumps({"video_id": job.video_id, "chunks": []}).encode("utf-8")
            tree = self._objects.put_bytes(tree_key, tree_blob, content_type="application/json")
            job.artifact_uris["context_tree"] = tree.uri or self._objects.uri_for(tree_key)

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


def create_worker_app(
    *,
    store: JobStore,
    object_store: ObjectStore,
) -> FastAPI:
    """Build the Cloud Run worker HTTP app (Pub/Sub push endpoint)."""
    processor = VideoProcessor(store, object_store)
    app = FastAPI(title="Meridian Video Worker", version="0.1.0")
    app.state.processor = processor

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "role": "worker"}

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
    return QueueMessage.from_bytes(raw)


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
