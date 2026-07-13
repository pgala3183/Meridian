"""OpenTelemetry setup for Cloud Trace / Cloud Monitoring."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Status, StatusCode, Tracer

logger = logging.getLogger(__name__)

_TRACER_NAME = "meridian"
_configured = False


def tracer() -> Tracer:
    return trace.get_tracer(_TRACER_NAME)


def configure_telemetry(*, service_name: str) -> None:
    """Install tracer + meter providers (GCP exporters when enabled)."""
    global _configured
    if _configured:
        return

    env = os.getenv("MERIDIAN_ENV", "development").lower()
    enabled = os.getenv("MERIDIAN_OTEL_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    if env == "test":
        enabled = os.getenv("MERIDIAN_OTEL_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
        }

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "meridian",
            "deployment.environment": env,
        }
    )

    provider = TracerProvider(resource=resource)
    if enabled:
        _attach_span_exporters(provider, env=env)
    trace.set_tracer_provider(provider)

    metric_readers = _metric_readers(env=env) if enabled else []
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=metric_readers))

    _configured = True
    logger.info("OpenTelemetry configured service=%s enabled=%s", service_name, enabled)


def _attach_span_exporters(provider: TracerProvider, *, env: str) -> None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if project and env == "production":
        try:
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

            exporter = CloudTraceSpanExporter(project_id=project)  # type: ignore[no-untyped-call]
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("Cloud Trace exporter attached project=%s", project)
            return
        except Exception:
            logger.exception("Cloud Trace exporter unavailable; using console")

    if os.getenv("MERIDIAN_OTEL_CONSOLE", "false").lower() in {"1", "true", "yes"}:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))


def _metric_readers(*, env: str) -> list[Any]:
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not (project and env == "production"):
        return []
    try:
        from opentelemetry.exporter.cloud_monitoring import (
            CloudMonitoringMetricsExporter,
        )
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        reader = PeriodicExportingMetricReader(
            CloudMonitoringMetricsExporter(project_id=project),
            export_interval_millis=60_000,
        )
        logger.info("Cloud Monitoring metrics exporter attached project=%s", project)
        return [reader]
    except Exception:
        logger.exception("Cloud Monitoring exporter unavailable")
        return []


@contextmanager
def pipeline_stage_span(
    stage_name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Create a span + record stage latency histogram for one pipeline stage."""
    meter = metrics.get_meter(_TRACER_NAME)
    histogram = meter.create_histogram(
        "meridian.pipeline.stage.duration",
        unit="s",
        description="Wall-clock duration of a Meridian pipeline stage",
    )
    started = time.perf_counter()
    with tracer().start_as_current_span(f"pipeline.stage.{stage_name}") as span:
        span.set_attribute("meridian.stage", stage_name)
        if attributes:
            for key, value in attributes.items():
                if value is not None:
                    span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            elapsed = time.perf_counter() - started
            histogram.record(elapsed, {"meridian.stage": stage_name})
            span.set_attribute("meridian.stage.duration_s", elapsed)
