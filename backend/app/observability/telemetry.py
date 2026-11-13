"""
Centralized OpenTelemetry Initialization and Lifecycle Management.

Configures TracerProvider, MeterProvider, Resource attributes, samplers,
and OTLP/in-memory exporters with graceful degradation and zero-downtime fault tolerance.
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

logger = logging.getLogger(__name__)

_TELEMETRY_MANAGER: TelemetryManager | None = None


class TelemetryManager:
    """
    Orchestrates OpenTelemetry TracerProvider and MeterProvider lifecycles.
    """

    def __init__(
        self,
        *,
        service_name: str = "ai-dev-platform",
        service_version: str = "1.0.0",
        environment: str = "development",
        enabled: bool = False,
        otlp_endpoint: str | None = None,
        otlp_headers: str | None = None,
        sample_rate: float = 1.0,
        metrics_enabled: bool = False,
        use_in_memory_exporter: bool = False,
    ) -> None:
        self.service_name = service_name
        self.service_version = service_version
        self.environment = environment
        self.enabled = enabled
        self.otlp_endpoint = otlp_endpoint
        self.otlp_headers = otlp_headers
        self.sample_rate = sample_rate
        self.metrics_enabled = metrics_enabled
        self.use_in_memory_exporter = use_in_memory_exporter

        self.tracer_provider: TracerProvider | None = None
        self.meter_provider: MeterProvider | None = None
        self.in_memory_exporter: InMemorySpanExporter | None = None
        self._is_initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def setup(self) -> bool:
        """Initialize OpenTelemetry tracer and meter providers."""
        if not self.enabled and not self.use_in_memory_exporter:
            logger.info("telemetry_disabled_by_config")
            return False

        try:
            resource = Resource.create({
                "service.name": self.service_name,
                "service.version": self.service_version,
                "deployment.environment.name": self.environment,
            })

            sampler = ParentBased(TraceIdRatioBased(max(0.0, min(1.0, self.sample_rate))))
            self.tracer_provider = TracerProvider(resource=resource, sampler=sampler)

            # Configure Span Exporter
            if self.use_in_memory_exporter:
                self.in_memory_exporter = InMemorySpanExporter()
                self.tracer_provider.add_span_processor(SimpleSpanProcessor(self.in_memory_exporter))
                logger.info("telemetry_using_in_memory_span_exporter")
            elif self.otlp_endpoint:
                try:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                    headers_dict = {}
                    if self.otlp_headers:
                        for item in self.otlp_headers.split(","):
                            if "=" in item:
                                k, v = item.split("=", 1)
                                headers_dict[k.strip()] = v.strip()
                    exporter = OTLPSpanExporter(endpoint=self.otlp_endpoint, headers=headers_dict, timeout=5)
                    self.tracer_provider.add_span_processor(BatchSpanProcessor(exporter, max_queue_size=2048))
                    logger.info("telemetry_otlp_span_exporter_initialized", extra={"endpoint": self.otlp_endpoint})
                except Exception as exc:
                    logger.warning("telemetry_otlp_exporter_init_failed", extra={"error": str(exc)})

            try:
                trace._TRACER_PROVIDER = None
                if hasattr(trace, "_TRACER_PROVIDER_SET_ONCE"):
                    trace._TRACER_PROVIDER_SET_ONCE._done = False
            except Exception:
                pass
            trace.set_tracer_provider(self.tracer_provider)

            # Configure Meter Provider if metrics are enabled
            if self.metrics_enabled or self.use_in_memory_exporter:
                self.meter_provider = MeterProvider(resource=resource)
                try:
                    import opentelemetry.metrics._internal as mi
                    mi._METER_PROVIDER = None
                    if hasattr(mi, "_METER_PROVIDER_SET_ONCE"):
                        mi._METER_PROVIDER_SET_ONCE._done = False
                except Exception:
                    pass
                metrics.set_meter_provider(self.meter_provider)
                logger.info("telemetry_meter_provider_initialized")

            self._is_initialized = True
            logger.info("telemetry_initialized_successfully", extra={
                "service": self.service_name,
                "version": self.service_version,
                "sample_rate": self.sample_rate,
            })
            return True
        except Exception as exc:
            logger.error("telemetry_setup_failed", extra={"error": str(exc)})
            self._is_initialized = False
            return False

    def shutdown(self) -> None:
        """Gracefully flush and shut down OpenTelemetry providers."""
        if self.tracer_provider:
            try:
                self.tracer_provider.shutdown()
            except Exception as exc:
                logger.debug("telemetry_tracer_shutdown_error", extra={"error": str(exc)})
        if self.meter_provider:
            try:
                self.meter_provider.shutdown()
            except Exception as exc:
                logger.debug("telemetry_meter_shutdown_error", extra={"error": str(exc)})
        self._is_initialized = False


def setup_telemetry(
    settings: Any = None,
    *,
    use_in_memory_exporter: bool = False,
    sample_rate: float | None = None,
) -> TelemetryManager:
    """Initialize or update process-wide TelemetryManager singleton."""
    global _TELEMETRY_MANAGER
    if settings is None:
        from app.core.config import get_settings
        settings = get_settings()

    manager = TelemetryManager(
        service_name=getattr(settings, "otel_service_name", "ai-dev-platform"),
        service_version=getattr(settings, "otel_service_version", "1.0.0"),
        environment=getattr(settings, "otel_environment", "development"),
        enabled=getattr(settings, "otel_enabled", False),
        otlp_endpoint=getattr(settings, "otel_exporter_otlp_endpoint", None),
        otlp_headers=getattr(settings, "otel_exporter_otlp_headers", None),
        sample_rate=sample_rate if sample_rate is not None else getattr(settings, "otel_trace_sample_rate", 1.0),
        metrics_enabled=getattr(settings, "otel_metrics_enabled", False),
        use_in_memory_exporter=use_in_memory_exporter,
    )
    manager.setup()
    _TELEMETRY_MANAGER = manager
    return manager


def get_telemetry_manager() -> TelemetryManager | None:
    return _TELEMETRY_MANAGER


def get_tracer(name: str = "app") -> trace.Tracer:
    return trace.get_tracer(name)


def get_meter(name: str = "app") -> metrics.Meter:
    return metrics.get_meter(name)


def shutdown_telemetry() -> None:
    global _TELEMETRY_MANAGER
    if _TELEMETRY_MANAGER is not None:
        _TELEMETRY_MANAGER.shutdown()
        _TELEMETRY_MANAGER = None
    try:
        trace._TRACER_PROVIDER = None
        if hasattr(trace, "_TRACER_PROVIDER_SET_ONCE"):
            trace._TRACER_PROVIDER_SET_ONCE._done = False
    except Exception:
        pass
    try:
        import opentelemetry.metrics._internal as mi
        mi._METER_PROVIDER = None
        if hasattr(mi, "_METER_PROVIDER_SET_ONCE"):
            mi._METER_PROVIDER_SET_ONCE._done = False
    except Exception:
        pass
