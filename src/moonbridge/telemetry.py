"""Lightweight OpenTelemetry wrapper with graceful no-op fallback."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from importlib import import_module
from typing import Any

logger = logging.getLogger("moonbridge.telemetry")

trace: Any | None = None
try:
    trace = import_module("opentelemetry.trace")
    _HAS_OTEL = True
except Exception:
    _HAS_OTEL = False

_TRACER_NAME = "moonbridge"


def _get_tracer() -> Any:
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
) -> Generator[Any, None, None]:
    """Context manager that creates an OTel span or no-ops.

    Args:
        name: Span name (e.g., "handle_tool/spawn_agent")
        attributes: Span attributes dict

    Yields:
        The span object (or None if OTel not installed)
    """
    try:
        tracer = _get_tracer()
    except Exception as exc:
        logger.debug("OpenTelemetry unavailable for span '%s': %s", name, exc)
        yield None
        return

    if tracer is None:
        yield None
        return

    try:
        span_context = tracer.start_as_current_span(name, attributes=attributes or {})
        span = span_context.__enter__()
    except Exception as exc:
        logger.debug("OpenTelemetry unavailable for span '%s': %s", name, exc)
        yield None
        return

    try:
        yield span
    except Exception as inner_exc:
        try:
            span_context.__exit__(type(inner_exc), inner_exc, inner_exc.__traceback__)
        except Exception as exit_exc:
            logger.debug("OpenTelemetry unavailable for span '%s': %s", name, exit_exc)
        raise
    else:
        try:
            span_context.__exit__(None, None, None)
        except Exception as exit_exc:
            logger.debug("OpenTelemetry unavailable for span '%s': %s", name, exit_exc)
