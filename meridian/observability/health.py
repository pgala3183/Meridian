"""Shared liveness / readiness helpers for API and worker services."""

from __future__ import annotations

from typing import Any


def health_payload(*, role: str) -> dict[str, str]:
    return {"status": "ok", "role": role}


def readiness_payload(
    *,
    role: str,
    checks: dict[str, bool],
) -> tuple[dict[str, Any], int]:
    """Return (body, http_status). Ready only when every check is True."""
    ready = all(checks.values())
    body: dict[str, Any] = {
        "status": "ready" if ready else "not_ready",
        "role": role,
        "checks": checks,
    }
    return body, 200 if ready else 503
