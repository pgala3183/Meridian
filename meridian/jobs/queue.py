"""Job queue abstraction and Pub/Sub publisher."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from meridian.jobs.models import VideoJob


@dataclass(frozen=True, slots=True)
class QueueMessage:
    """Payload published for async video processing."""

    job_id: str
    video_id: str
    user_id: str
    stage_hint: str = "ingest"

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "job_id": self.job_id,
                "video_id": self.video_id,
                "user_id": self.user_id,
                "stage_hint": self.stage_hint,
            },
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> QueueMessage:
        data = json.loads(raw.decode("utf-8"))
        return cls(
            job_id=str(data["job_id"]),
            video_id=str(data["video_id"]),
            user_id=str(data["user_id"]),
            stage_hint=str(data.get("stage_hint", "ingest")),
        )

    @classmethod
    def from_job(cls, job: VideoJob, *, stage_hint: str = "ingest") -> QueueMessage:
        return cls(
            job_id=job.job_id,
            video_id=job.video_id,
            user_id=job.user_id,
            stage_hint=stage_hint,
        )


class JobQueue(ABC):
    """Publish side of the async processing bus."""

    @abstractmethod
    def enqueue(self, message: QueueMessage) -> str:
        """Publish a job message; return a broker message id when available."""


class InMemoryJobQueue(JobQueue):
    """Test double that records messages in-process."""

    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []

    def enqueue(self, message: QueueMessage) -> str:
        self.messages.append(message)
        return f"mem-{len(self.messages)}"


class PubSubJobQueue(JobQueue):
    """Google Cloud Pub/Sub publisher for fan-out capable job dispatch.

    A single topic can fan out to multiple subscriptions (transcription,
    embedding, indexing) without the API knowing about worker topology.
    """

    def __init__(
        self,
        topic_path: str,
        *,
        publisher: Any | None = None,
    ) -> None:
        if not topic_path:
            raise ValueError("PubSubJobQueue requires topic_path")
        self.topic_path = topic_path
        self._publisher = publisher

    def _get_publisher(self) -> Any:
        if self._publisher is None:
            from google.cloud import pubsub_v1  # type: ignore[attr-defined]

            self._publisher = pubsub_v1.PublisherClient()
        return self._publisher

    def enqueue(self, message: QueueMessage) -> str:
        publisher = self._get_publisher()
        future = publisher.publish(
            self.topic_path,
            message.to_bytes(),
            job_id=message.job_id,
            video_id=message.video_id,
            stage_hint=message.stage_hint,
        )
        return str(future.result())
