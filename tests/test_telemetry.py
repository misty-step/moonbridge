"""Tests for moonbridge.telemetry module."""

import uuid
from unittest.mock import MagicMock, patch

from moonbridge.telemetry import generate_request_id, get_tracer, trace_span


class TestGenerateRequestId:
    def test_returns_valid_uuid4(self) -> None:
        rid = generate_request_id()
        parsed = uuid.UUID(rid, version=4)
        assert str(parsed) == rid

    def test_unique_per_call(self) -> None:
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100


class TestGetTracer:
    def test_returns_none_when_otel_missing(self) -> None:
        with patch("moonbridge.telemetry._HAS_OTEL", False):
            assert get_tracer() is None

    def test_returns_tracer_when_otel_available(self) -> None:
        mock_tracer = MagicMock()
        with (
            patch("moonbridge.telemetry._HAS_OTEL", True),
            patch("moonbridge.telemetry.trace") as mock_trace,
        ):
            mock_trace.get_tracer.return_value = mock_tracer
            result = get_tracer()
            assert result is mock_tracer
            mock_trace.get_tracer.assert_called_once_with("moonbridge")


class TestTraceSpan:
    def test_yields_none_when_no_otel(self) -> None:
        with patch("moonbridge.telemetry._HAS_OTEL", False), trace_span("test") as span:
            assert span is None

    def test_creates_span_when_otel_available(self) -> None:
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_context = mock_tracer.start_as_current_span.return_value
        mock_context.__enter__.return_value = mock_span
        mock_context.__exit__.return_value = None

        with trace_span(
            "test", attributes={"key": "val"}, parent_tracer=mock_tracer
        ) as span:
            assert span is mock_span
        mock_tracer.start_as_current_span.assert_called_once_with(
            "test", attributes={"key": "val"}
        )
