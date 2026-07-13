"""Unit tests for request_id threading on queue messages."""

from meridian.jobs.models import VideoJob
from meridian.jobs.queue import QueueMessage


def test_queue_message_round_trips_request_id() -> None:
    msg = QueueMessage(
        job_id="j1",
        video_id="v1",
        user_id="u1",
        request_id="req-99",
    )
    restored = QueueMessage.from_bytes(msg.to_bytes())
    assert restored.request_id == "req-99"


def test_queue_message_from_job_copies_request_id() -> None:
    job = VideoJob(user_id="u", video_id="v", request_id="from-http")
    msg = QueueMessage.from_job(job)
    assert msg.request_id == "from-http"


def test_queue_message_back_compat_without_request_id() -> None:
    raw = b'{"job_id":"j","video_id":"v","user_id":"u","stage_hint":"ingest"}'
    msg = QueueMessage.from_bytes(raw)
    assert msg.request_id is None
