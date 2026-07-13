"""API tests for async video enqueue / status / rate limits."""

from __future__ import annotations

import os

os.environ["MERIDIAN_ENV"] = "test"

from fastapi.testclient import TestClient

from meridian.api.main import create_app
from meridian.api.rate_limit import RateLimitConfig, RateLimitExceeded, TokenBucketRateLimiter
from meridian.jobs.memory_store import InMemoryJobStore
from meridian.jobs.queue import InMemoryJobQueue
from meridian.storage.local_backend import LocalObjectStore


def _client(tmp_path):
    store = InMemoryJobStore()
    queue = InMemoryJobQueue()
    objects = LocalObjectStore(tmp_path)
    limiter = TokenBucketRateLimiter(RateLimitConfig(capacity=5, refill_per_second=100.0))
    app = create_app(
        job_store=store,
        job_queue=queue,
        object_store=objects,
        rate_limiter=limiter,
    )
    return TestClient(app), store, queue


def test_enqueue_returns_job_id(tmp_path) -> None:
    client, store, queue = _client(tmp_path)
    with client:
        resp = client.post(
            "/videos",
            json={"video_id": "demo", "user_id": "alice"},
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"]
    assert body["status"] == "queued"
    assert "/status" in body["poll_url"]
    assert store.get_job(body["job_id"]) is not None
    assert len(queue.messages) == 1


def test_get_status(tmp_path) -> None:
    client, _store, _queue = _client(tmp_path)
    with client:
        created = client.post("/videos", json={"video_id": "demo2", "user_id": "bob"}).json()
        status = client.get(f"/videos/{created['job_id']}/status")
    assert status.status_code == 200
    assert status.json()["video_id"] == "demo2"


def test_status_404(tmp_path) -> None:
    client, _, _ = _client(tmp_path)
    with client:
        resp = client.get("/videos/does-not-exist/status")
    assert resp.status_code == 404


def test_ask_requires_succeeded_job(tmp_path) -> None:
    client, _store, _queue = _client(tmp_path)
    with client:
        created = client.post("/videos", json={"video_id": "ask-me", "user_id": "demo-web"}).json()
        import time

        job_id = created["job_id"]
        for _ in range(40):
            status = client.get(f"/videos/{job_id}/status").json()
            if status["status"] == "succeeded":
                break
            time.sleep(0.05)
        resp = client.post(f"/videos/{job_id}/ask", json={"question": "What about the cache?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["citations"]
    assert body["citations"][0]["start_time"] >= 0


def test_rate_limiter_blocks() -> None:
    limiter = TokenBucketRateLimiter(RateLimitConfig(capacity=2, refill_per_second=0.0))
    limiter.allow("user:x")
    limiter.allow("user:x")
    try:
        limiter.allow("user:x")
        raised = False
    except RateLimitExceeded:
        raised = True
    assert raised


def test_api_rate_limit_returns_429(tmp_path) -> None:
    store = InMemoryJobStore()
    queue = InMemoryJobQueue()
    objects = LocalObjectStore(tmp_path)
    limiter = TokenBucketRateLimiter(RateLimitConfig(capacity=1, refill_per_second=0.0))
    app = create_app(
        job_store=store,
        job_queue=queue,
        object_store=objects,
        rate_limiter=limiter,
    )
    with TestClient(app) as client:
        assert client.post("/videos", json={"video_id": "a", "user_id": "same"}).status_code == 202
        second = client.post("/videos", json={"video_id": "b", "user_id": "same"})
    assert second.status_code == 429
