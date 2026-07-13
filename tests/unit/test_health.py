"""Unit tests for API health endpoint."""

import os

os.environ["MERIDIAN_ENV"] = "test"

from fastapi.testclient import TestClient

from meridian.api.main import create_app
from meridian.api.rate_limit import TokenBucketRateLimiter
from meridian.jobs.memory_store import InMemoryJobStore
from meridian.jobs.queue import InMemoryJobQueue


def test_health(tmp_path) -> None:
    from meridian.storage.local_backend import LocalObjectStore

    app = create_app(
        job_store=InMemoryJobStore(),
        job_queue=InMemoryJobQueue(),
        object_store=LocalObjectStore(tmp_path),
        rate_limiter=TokenBucketRateLimiter(),
    )
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
