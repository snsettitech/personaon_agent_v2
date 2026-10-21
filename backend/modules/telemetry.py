"""Central OTEL telemetry adapter.

No-op when OTEL_EXPORTER_OTLP_ENDPOINT is unset — nothing breaks without it.
Call setup_telemetry() once at app startup (main.py lifespan).
All services import get_tracer() from here so the exporter is wired in one place.

Supported backends (controlled by OTEL_EXPORTER_OTLP_ENDPOINT):
  - http://localhost:6006/v1/traces  → Arize Phoenix (local dev)
  - Any OTLP-compatible endpoint     → Datadog, Jaeger, Grafana Tempo, etc.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def setup_telemetry() -> None:
    """Configure the global OTEL TracerProvider. Safe to call multiple times."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.debug("[Telemetry] OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        # Use HTTP exporter for http(s):// endpoints, gRPC exporter otherwise
        if endpoint.startswith("http"):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider = TracerProvider()
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        trace.set_tracer_provider(provider)
        logger.info("[Telemetry] OTEL tracing enabled endpoint=%s", endpoint)
    except ImportError:
        logger.warning(
            "[Telemetry] opentelemetry packages not installed — tracing skipped"
        )
    except Exception as exc:
        logger.warning("[Telemetry] failed to configure OTEL: %s", exc)


def get_tracer(name: str):
    """Return an OTEL tracer. Returns a no-op tracer when tracing is not configured."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


class _NoOpSpan:
    """No-op span — implements the methods OTEL callers commonly use so we
    don't AttributeError on the dark path (no exporter configured)."""

    def set_attribute(self, key: str, value: object) -> None:
        pass

    def set_attributes(self, attributes: dict) -> None:
        pass

    def record_exception(self, exc: BaseException, **_kwargs) -> None:
        pass

    def set_status(self, *_args, **_kwargs) -> None:
        pass

    def add_event(self, *_args, **_kwargs) -> None:
        pass

    def update_name(self, *_args, **_kwargs) -> None:
        pass

    def is_recording(self) -> bool:
        return False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _NoOpTracer:
    def start_as_current_span(self, name: str, **_kwargs):
        return _NoOpSpan()

    def start_span(self, name: str, **_kwargs):
        return _NoOpSpan()
