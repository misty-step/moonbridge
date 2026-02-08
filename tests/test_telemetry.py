"""Tests for moonbridge.telemetry module."""

import importlib
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

from moonbridge.telemetry import _get_tracer, generate_request_id, trace_span


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
            assert _get_tracer() is None

    def test_returns_tracer_when_otel_available(self) -> None:
        mock_tracer = MagicMock()
        with (
            patch("moonbridge.telemetry._HAS_OTEL", True),
            patch("moonbridge.telemetry.trace") as mock_trace,
        ):
            mock_trace.get_tracer.return_value = mock_tracer
            result = _get_tracer()
            assert result is mock_tracer
            mock_trace.get_tracer.assert_called_once_with("moonbridge")

    def test_handles_non_import_error_during_import(self, monkeypatch: Any) -> None:
        telemetry = importlib.import_module("moonbridge.telemetry")
        original_import_module = importlib.import_module

        with monkeypatch.context() as patch_context:

            def broken_import(name: str, package: str | None = None) -> Any:
                if name == "opentelemetry.trace":
                    raise AttributeError("broken opentelemetry install")
                return original_import_module(name, package)

            patch_context.setattr(importlib, "import_module", broken_import)
            reloaded = importlib.reload(telemetry)

        assert reloaded._HAS_OTEL is False
        assert reloaded._get_tracer() is None
        importlib.reload(telemetry)


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

        with (
            patch("moonbridge.telemetry._get_tracer", return_value=mock_tracer),
            trace_span("test", attributes={"key": "val"}) as span,
        ):
            assert span is mock_span
        mock_tracer.start_as_current_span.assert_called_once_with(
            "test", attributes={"key": "val"}
        )

    def test_trace_span_catches_otel_exception(self) -> None:
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.side_effect = RuntimeError("otel broken")

        with (
            patch("moonbridge.telemetry._get_tracer", return_value=mock_tracer),
            trace_span("test") as span,
        ):
            assert span is None
