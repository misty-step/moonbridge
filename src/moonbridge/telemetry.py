"""Lightweight OpenTelemetry wrapper with graceful no-op fallback."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from importlib import import_module
from typing import Any

trace: Any | None = None
try:
    trace = import_module("opentelemetry.trace")
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False

_TRACER_NAME = "moonbridge"


def get_tracer() -> Any:
    """Return OTel tracer or None when not installed."""
    if _HAS_OTEL and trace is not None:
        return trace.get_tracer(_TRACER_NAME)
    return None


def generate_request_id() -> str:
    """Generate a UUID4 request ID for correlating tool calls."""
    return str(uuid.uuid4())


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    parent_tracer: Any = None,
) -> Generator[Any, None, None]:
    """Context manager that creates an OTel span or no-ops.

    Args:
        name: Span name (e.g., "handle_tool/spawn_agent")
        attributes: Span attributes dict
        parent_tracer: Tracer instance (from get_tracer). If None, gets default.

    Yields:
        The span object (or None if OTel not installed)
    """
    tracer = parent_tracer or get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span
