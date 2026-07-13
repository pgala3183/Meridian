"""FastAPI application entrypoint."""

from fastapi import FastAPI

app = FastAPI(
    title="Meridian",
    description="Long-form video intelligence platform",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}
