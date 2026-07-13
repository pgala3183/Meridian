"""Unit tests for job store, queue, and video processor."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient

from meridian.jobs.memory_store import InMemoryJobStore
from meridian.jobs.models import JobStatus, VideoJob
from meridian.jobs.queue import InMemoryJobQueue, QueueMessage
from meridian.storage.local_backend import LocalObjectStore
from meridian.workers.video_processor import VideoProcessor, create_worker_app


def test_in_memory_job_store_and_queue() -> None:
    store = InMemoryJobStore()
    queue = InMemoryJobQueue()
    job = VideoJob(user_id="u1", video_id="v1")
    store.create_job(job)
    mid = queue.enqueue(QueueMessage.from_job(job))
    assert mid.startswith("mem-")
    assert store.get_job(job.job_id) is not None
    assert len(queue.messages) == 1


def test_video_processor_writes_artifacts(tmp_path: Path) -> None:
    store = InMemoryJobStore()
    objects = LocalObjectStore(tmp_path)
    job = store.create_job(VideoJob(user_id="u1", video_id="vid-9"))
    processor = VideoProcessor(store, objects)
    result = processor.process(QueueMessage.from_job(job))
    assert result.status is JobStatus.SUCCEEDED
    assert "transcript" in result.artifact_uris
    assert "context_tree" in result.artifact_uris


def test_worker_pubsub_push_endpoint(tmp_path: Path) -> None:
    store = InMemoryJobStore()
    objects = LocalObjectStore(tmp_path)
    job = store.create_job(VideoJob(user_id="u1", video_id="vid-push"))
    app = create_worker_app(store=store, object_store=objects)
    message = QueueMessage.from_job(job)
    envelope = {
        "message": {
            "data": base64.b64encode(message.to_bytes()).decode("ascii"),
            "messageId": "1",
        }
    }
    with TestClient(app) as client:
        resp = client.post("/pubsub/push", json=envelope)
    assert resp.status_code == 200
    updated = store.get_job(job.job_id)
    assert updated is not None
    assert updated.status is JobStatus.SUCCEEDED


def test_queue_message_roundtrip() -> None:
    raw = QueueMessage(job_id="j", video_id="v", user_id="u", stage_hint="embed").to_bytes()
    parsed = QueueMessage.from_bytes(raw)
    assert parsed.job_id == "j"
    assert json.loads(raw.decode())["stage_hint"] == "embed"
