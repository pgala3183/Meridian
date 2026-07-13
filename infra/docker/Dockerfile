FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY meridian ./meridian

RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080

# Default: API. Worker image overrides CMD in Cloud Run / compose.
CMD ["uvicorn", "meridian.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
