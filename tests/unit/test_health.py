"""Unit tests for API health endpoint."""

import os

from fastapi.testclient import TestClient

# Ensure lifespan boot uses the permissive test environment.
os.environ.setdefault("MERIDIAN_ENV", "test")

from meridian.api.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
