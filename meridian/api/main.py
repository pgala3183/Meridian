"""FastAPI application entrypoint."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from meridian.api.rate_limit import RateLimitConfig, TokenBucketRateLimiter  # noqa: E402
from meridian.api.routes import videos as videos_routes  # noqa: E402
from meridian.jobs.firestore_store import FirestoreJobStore  # noqa: E402
from meridian.jobs.memory_store import InMemoryJobStore  # noqa: E402
from meridian.jobs.queue import InMemoryJobQueue, PubSubJobQueue  # noqa: E402
from meridian.observability.health import health_payload, readiness_payload  # noqa: E402
from meridian.observability.logging import configure_logging  # noqa: E402
from meridian.observability.middleware import RequestContextMiddleware  # noqa: E402
from meridian.observability.tracing import configure_telemetry  # noqa: E402
from meridian.secrets import (  # noqa: E402
    AppEnvironment,
    SecretError,
    assert_boot_secrets,
    detect_environment,
    load_runtime_secrets,
)
from meridian.storage.base import StorageBackendName  # noqa: E402
from meridian.storage.factory import StorageConfig, create_object_store  # noqa: E402


def _cors_origins() -> list[str]:
    raw = os.getenv("MERIDIAN_CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _boot_secrets() -> None:
    """Refuse to start if secrets are missing or look like placeholders."""
    env = detect_environment()
    if env is AppEnvironment.TEST:
        return
    secrets = load_runtime_secrets(
        environment=env,
        require_gcp_project=(env is AppEnvironment.PRODUCTION),
    )
    assert_boot_secrets(secrets)


def _build_job_store() -> InMemoryJobStore | FirestoreJobStore:
    backend = os.getenv("MERIDIAN_JOB_STORE", "memory").lower()
    if backend == "firestore":
        return FirestoreJobStore(project=os.getenv("GOOGLE_CLOUD_PROJECT"))
    return InMemoryJobStore()


def _build_queue() -> InMemoryJobQueue | PubSubJobQueue:
    topic = os.getenv("MERIDIAN_PUBSUB_TOPIC", "")
    if topic:
        return PubSubJobQueue(topic)
    return InMemoryJobQueue()


def _build_object_store() -> object:
    backend = os.getenv("MERIDIAN_STORAGE_BACKEND", "local").lower()
    name = StorageBackendName.GCS if backend == "gcs" else StorageBackendName.LOCAL
    return create_object_store(
        StorageConfig(
            backend=name,
            local_root=os.getenv("MERIDIAN_LOCAL_STORAGE", ".meridian-data/objects"),
            gcs_bucket=os.getenv("MERIDIAN_GCS_BUCKET"),
            gcs_prefix=os.getenv("MERIDIAN_GCS_PREFIX", "meridian"),
        )
    )


def _build_rate_limiter() -> TokenBucketRateLimiter:
    redis_url = os.getenv("REDIS_URL")
    client = None
    if redis_url:
        import redis

        client = redis.Redis.from_url(redis_url)
    return TokenBucketRateLimiter(
        RateLimitConfig(
            capacity=float(os.getenv("MERIDIAN_RL_CAPACITY", "30")),
            refill_per_second=float(os.getenv("MERIDIAN_RL_REFILL", "0.5")),
        ),
        redis_client=client,
    )


def _readiness_checks(app: FastAPI) -> dict[str, bool]:
    checks: dict[str, bool] = {
        "job_store": getattr(app.state, "job_store", None) is not None,
        "job_queue": getattr(app.state, "job_queue", None) is not None,
        "object_store": getattr(app.state, "object_store", None) is not None,
        "rate_limiter": getattr(app.state, "rate_limiter", None) is not None,
    }
    return checks


def create_app(
    *,
    job_store: object | None = None,
    job_queue: object | None = None,
    object_store: object | None = None,
    rate_limiter: TokenBucketRateLimiter | None = None,
) -> FastAPI:
    """Application factory for production and tests."""
    configure_logging(service="meridian-api")
    configure_telemetry(service_name="meridian-api")

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        env = detect_environment()
        if env is not AppEnvironment.TEST:
            try:
                _boot_secrets()
            except SecretError as exc:
                raise RuntimeError(f"Meridian startup aborted: {exc}") from exc
        app.state.job_store = job_store or _build_job_store()
        app.state.job_queue = job_queue or _build_queue()
        app.state.object_store = object_store or _build_object_store()
        app.state.rate_limiter = rate_limiter or _build_rate_limiter()
        yield

    application = FastAPI(
        title="Meridian",
        description="Long-form video intelligence platform",
        version="0.1.0",
        lifespan=_lifespan,
    )
    application.add_middleware(RequestContextMiddleware, service="api")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(videos_routes.router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return health_payload(role="api")

    @application.get("/ready")
    def ready(response: Response) -> dict[str, Any]:
        body, status = readiness_payload(role="api", checks=_readiness_checks(application))
        response.status_code = status
        return body

    return application


app = create_app()
