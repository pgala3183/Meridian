"""Health and readiness endpoint tests."""

import os

os.environ["MERIDIAN_ENV"] = "test"

from fastapi.testclient import TestClient

from meridian.api.main import create_app
from meridian.api.rate_limit import TokenBucketRateLimiter
from meridian.jobs.memory_store import InMemoryJobStore
from meridian.jobs.queue import InMemoryJobQueue
from meridian.storage.local_backend import LocalObjectStore
from meridian.workers.video_processor import create_worker_app


def _api(tmp_path):
    return create_app(
        job_store=InMemoryJobStore(),
        job_queue=InMemoryJobQueue(),
        object_store=LocalObjectStore(tmp_path),
        rate_limiter=TokenBucketRateLimiter(),
    )


def test_health(tmp_path) -> None:
    with TestClient(_api(tmp_path)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["role"] == "api"


def test_ready(tmp_path) -> None:
    with TestClient(_api(tmp_path)) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["job_store"] is True


def test_request_id_header_echo(tmp_path) -> None:
    with TestClient(_api(tmp_path)) as client:
        response = client.get("/health", headers={"X-Request-ID": "demo-req-1"})
    assert response.headers.get("X-Request-ID") == "demo-req-1"


def test_worker_health_and_ready(tmp_path) -> None:
    app = create_worker_app(
        store=InMemoryJobStore(),
        object_store=LocalObjectStore(tmp_path / "worker"),
    )
    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    assert health.status_code == 200
    assert health.json()["role"] == "worker"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
