"""Cloud Logging-compatible structured JSON logs."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

from meridian.observability.context import get_job_id, get_request_id

_SEVERITY = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}


class CloudJsonFormatter(logging.Formatter):
    """Emit one JSON object per line (Cloud Logging / fluentd friendly)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "severity": _SEVERITY.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
        }
        request_id = get_request_id() or getattr(record, "request_id", None)
        job_id = get_job_id() or getattr(record, "job_id", None)
        if request_id:
            payload["request_id"] = request_id
        if job_id:
            payload["job_id"] = job_id
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("http_method", "http_path", "http_status", "latency_ms", "service"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(*, service: str = "meridian", level: str | None = None) -> None:
    """Configure root logging once for API / worker processes."""
    root = logging.getLogger()
    if getattr(root, "_meridian_configured", False):
        return

    resolved = level if level is not None else os.getenv("MERIDIAN_LOG_LEVEL", "INFO")
    log_level = resolved.upper()
    handler = logging.StreamHandler(sys.stdout)
    use_json = os.getenv("MERIDIAN_LOG_FORMAT", "json").lower() != "text"
    if use_json:
        handler.setFormatter(CloudJsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    root._meridian_configured = True  # type: ignore[attr-defined]
    logging.getLogger(__name__).debug("Logging configured for service=%s", service)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
