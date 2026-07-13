"""FastAPI middleware for request IDs and structured access logs."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from meridian.observability.context import clear_context, set_job_id, set_request_id
from meridian.observability.logging import get_logger

logger = get_logger("meridian.http")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind request_id for the request lifecycle and echo it on responses."""

    def __init__(self, app: object, *, service: str = "api") -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.service = service

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming.strip() if incoming else str(uuid.uuid4())
        set_request_id(request_id)
        set_job_id(None)
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = (time.perf_counter() - started) * 1000.0
            logger.exception(
                "Unhandled error",
                extra={
                    "service": self.service,
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "latency_ms": round(latency_ms, 2),
                    "request_id": request_id,
                },
            )
            clear_context()
            raise

        latency_ms = (time.perf_counter() - started) * 1000.0
        response.headers[REQUEST_ID_HEADER] = request_id
        if request.url.path not in {"/health", "/ready"}:
            logger.info(
                "request completed",
                extra={
                    "service": self.service,
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "latency_ms": round(latency_ms, 2),
                    "request_id": request_id,
                },
            )
        clear_context()
        return response
