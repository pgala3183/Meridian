"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from meridian.secrets import (
    AppEnvironment,
    SecretError,
    assert_boot_secrets,
    detect_environment,
    load_runtime_secrets,
)


def _boot_secrets() -> None:
    """Refuse to start if secrets are missing or look like placeholders."""
    env = detect_environment()
    if env is AppEnvironment.TEST:
        # Unit/integration tests inject providers; skip external secret requirements.
        return
    secrets = load_runtime_secrets(
        environment=env,
        require_gcp_project=(env is AppEnvironment.PRODUCTION),
    )
    assert_boot_secrets(secrets)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        _boot_secrets()
    except SecretError as exc:
        # Fail closed — do not serve traffic with unsafe secret configuration.
        raise RuntimeError(f"Meridian startup aborted: {exc}") from exc
    yield


app = FastAPI(
    title="Meridian",
    description="Long-form video intelligence platform",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
