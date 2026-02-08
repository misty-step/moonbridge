import importlib
import json
from typing import Any

import pytest

server_module = importlib.import_module("moonbridge.server")
_json_text = server_module._json_text
_enforce = server_module._enforce_response_limit


class TestEnforceResponseLimit:
    """Unit tests for _enforce_response_limit."""

    def test_under_limit_passes_through(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 10_000)
        content = _json_text({"status": "success", "output": "hello"})

        result = _enforce(content, "spawn_agent")

        assert result is content

    def test_oversized_replaced_with_circuit_breaker(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 50)
        content = _json_text({"status": "success", "output": "x" * 500})

        result = _enforce(content, "spawn_agent")
        payload = json.loads(result[0].text)

        assert payload["status"] == "error"
        assert payload["message"] == "Response payload too large"
        assert payload["circuit_breaker"]["triggered"] is True
        assert payload["circuit_breaker"]["max_bytes"] == 50
        assert payload["circuit_breaker"]["tool"] == "spawn_agent"

    def test_metadata_reports_original_size(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 50)
        content = _json_text({"output": "y" * 500})
        expected_bytes = len(
            json.dumps(
                [{"type": c.type, "text": c.text} for c in content],
                ensure_ascii=True,
            )
        )

        result = _enforce(content, "test_tool")
        payload = json.loads(result[0].text)

        assert payload["circuit_breaker"]["original_bytes"] == expected_bytes

    def test_exactly_at_limit_passes_through(self, monkeypatch: Any) -> None:
        content = _json_text({"ok": True})
        serialized = json.dumps(
            [{"type": c.type, "text": c.text} for c in content],
            ensure_ascii=True,
        )
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", len(serialized))

        result = _enforce(content, "spawn_agent")

        assert result is content

    def test_one_byte_over_limit_triggers(self, monkeypatch: Any) -> None:
        content = _json_text({"ok": True})
        serialized = json.dumps(
            [{"type": c.type, "text": c.text} for c in content],
            ensure_ascii=True,
        )
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", len(serialized) - 1)

        result = _enforce(content, "spawn_agent")
        payload = json.loads(result[0].text)

        assert payload["circuit_breaker"]["triggered"] is True

    def test_tool_name_truncated_in_fallback(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 50)
        content = _json_text({"output": "x" * 500})
        long_name = "a" * 500

        result = _enforce(content, long_name)
        payload = json.loads(result[0].text)

        assert len(payload["circuit_breaker"]["tool"]) == 200


class TestCircuitBreakerIntegration:
    """Integration tests via handle_tool + _enforce_response_limit."""

    @pytest.mark.asyncio
    async def test_normal_response_passes_through(
        self, mock_popen: Any, mock_which_kimi: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 10_000)

        raw = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
        result = _enforce(raw, "spawn_agent")
        payload = json.loads(result[0].text)

        assert payload["status"] == "success"
        assert "circuit_breaker" not in payload

    @pytest.mark.asyncio
    async def test_oversized_spawn_agent(
        self, mock_popen: Any, mock_which_kimi: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 100)
        process = mock_popen.return_value
        process.communicate.return_value = ("x" * 2_000, "")
        process.returncode = 0

        raw = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
        result = _enforce(raw, "spawn_agent")
        payload = json.loads(result[0].text)

        assert payload["circuit_breaker"]["triggered"] is True

    @pytest.mark.asyncio
    async def test_env_var_configures_limit(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 1000)

        content = _json_text({"output": "z" * 4_000})
        result = _enforce(content, "spawn_agent")
        payload = json.loads(result[0].text)

        assert payload["circuit_breaker"]["max_bytes"] == 1000
