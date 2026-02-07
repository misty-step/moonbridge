import importlib
import json
from typing import Any

import pytest

from moonbridge.adapters.base import AgentResult

server_module = importlib.import_module("moonbridge.server")


def _content_size_bytes(content: list[Any]) -> int:
    return len(
        json.dumps(
            [{"type": item.type, "text": item.text} for item in content],
            ensure_ascii=True,
        )
    )


@pytest.mark.asyncio
async def test_response_under_limit_passes_through(
    mock_popen: Any, mock_which_kimi: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 10_000)

    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "success"
    assert "circuit_breaker" not in payload


@pytest.mark.asyncio
async def test_oversized_response_replaced_with_circuit_breaker(
    mock_popen: Any, mock_which_kimi: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 100)
    process = mock_popen.return_value
    process.communicate.return_value = ("x" * 2_000, "")
    process.returncode = 0

    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"
    assert payload["message"] == "Response payload too large"
    assert payload["circuit_breaker"]["triggered"] is True


@pytest.mark.asyncio
async def test_circuit_breaker_metadata_matches_original_payload_size(
    mock_which_kimi: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 100)
    deterministic = AgentResult(
        status="success",
        output="y" * 500,
        stderr=None,
        returncode=0,
        duration_ms=1,
        agent_index=0,
    )

    def fake_run(
        _adapter: Any,
        prompt: str,
        thinking: bool,
        cwd: str,
        timeout_seconds: int,
        agent_index: int,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> AgentResult:
        return deterministic

    monkeypatch.setattr(server_module, "_run_cli_sync", fake_run)

    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)
    expected_content = server_module._json_text(deterministic.to_dict())
    expected_bytes = _content_size_bytes(expected_content)

    assert payload["circuit_breaker"]["original_bytes"] == expected_bytes
    assert payload["circuit_breaker"]["max_bytes"] == 100
    assert payload["circuit_breaker"]["tool"] == "spawn_agent"


@pytest.mark.asyncio
async def test_circuit_breaker_applies_to_spawn_agents_parallel(
    mock_which_kimi: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(server_module, "MAX_RESPONSE_BYTES", 100)

    def fake_run(
        _adapter: Any,
        prompt: str,
        thinking: bool,
        cwd: str,
        timeout_seconds: int,
        agent_index: int,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> AgentResult:
        return AgentResult(
            status="success",
            output=prompt * 300,
            stderr=None,
            returncode=0,
            duration_ms=1,
            agent_index=agent_index,
        )

    monkeypatch.setattr(server_module, "_run_cli_sync", fake_run)

    result = await server_module.handle_tool(
        "spawn_agents_parallel",
        {"agents": [{"prompt": "one"}, {"prompt": "two"}]},
    )
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"
    assert payload["message"] == "Response payload too large"
    assert payload["circuit_breaker"]["tool"] == "spawn_agents_parallel"


@pytest.mark.asyncio
async def test_max_response_bytes_env_var_is_respected(
    mock_which_kimi: Any, monkeypatch: Any
) -> None:
    monkeypatch.setenv("MOONBRIDGE_MAX_RESPONSE_BYTES", "1000")
    reloaded = importlib.reload(server_module)

    def fake_run(
        _adapter: Any,
        prompt: str,
        thinking: bool,
        cwd: str,
        timeout_seconds: int,
        agent_index: int,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> AgentResult:
        return AgentResult(
            status="success",
            output="z" * 4_000,
            stderr=None,
            returncode=0,
            duration_ms=1,
            agent_index=agent_index,
        )

    monkeypatch.setattr(reloaded, "_run_cli_sync", fake_run)

    result = await reloaded.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert reloaded.MAX_RESPONSE_BYTES == 1000
    assert payload["circuit_breaker"]["max_bytes"] == 1000

    monkeypatch.delenv("MOONBRIDGE_MAX_RESPONSE_BYTES", raising=False)
    importlib.reload(reloaded)
