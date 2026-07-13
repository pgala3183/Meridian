"""Observability helpers: JSON logs, context, pipeline spans."""

from __future__ import annotations

import json
import logging
import os

os.environ["MERIDIAN_ENV"] = "test"
os.environ["MERIDIAN_OTEL_ENABLED"] = "false"

from meridian.observability.context import clear_context, get_request_id, set_request_id
from meridian.observability.logging import CloudJsonFormatter, configure_logging
from meridian.observability.tracing import configure_telemetry, pipeline_stage_span, tracer


def test_json_formatter_includes_request_id() -> None:
    set_request_id("req-abc")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        payload = json.loads(CloudJsonFormatter().format(record))
        assert payload["severity"] == "INFO"
        assert payload["message"] == "hello"
        assert payload["request_id"] == "req-abc"
        assert "timestamp" in payload
    finally:
        clear_context()


def test_configure_logging_idempotent() -> None:
    configure_logging(service="test")
    configure_logging(service="test")
    assert get_request_id() is None


def test_pipeline_stage_span_records_without_error() -> None:
    configure_telemetry(service_name="meridian-test")
    with pipeline_stage_span("semantic_chunk", attributes={"meridian.video_id": "v1"}):
        pass
    with tracer().start_as_current_span("pipeline.run"):
        assert True
