import importlib
import json
import threading
import time
from subprocess import TimeoutExpired

import pytest

server_module = importlib.import_module("moonbridge.server")


@pytest.mark.asyncio
async def test_spawn_agent_calls_kimi_cli(mock_popen):
    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "success"
    args, _kwargs = mock_popen.call_args
    assert args[0] == ["kimi", "--print", "--prompt", "Hello"]
    assert "--thinking" not in args[0]


@pytest.mark.asyncio
async def test_spawn_agent_thinking_adds_flag(mock_popen):
    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello", "thinking": True})
    payload = json.loads(result[0].text)

    assert payload["status"] == "success"
    args, _kwargs = mock_popen.call_args
    assert "--thinking" in args[0]


@pytest.mark.asyncio
async def test_spawn_agents_parallel_runs_concurrently(monkeypatch):
    starts: list[float] = []
    lock = threading.Lock()
    event = threading.Event()

    def fake_run(_adapter, prompt, thinking, cwd, timeout_seconds, agent_index):
        with lock:
            starts.append(time.monotonic())
            if len(starts) == 2:
                event.set()
        event.wait(0.2)
        return {
            "status": "success",
            "output": prompt,
            "stderr": None,
            "returncode": 0,
            "duration_ms": 1,
            "agent_index": agent_index,
        }

    monkeypatch.setattr(server_module, "_run_cli_sync", fake_run)
    monkeypatch.setattr(server_module, "MAX_PARALLEL_AGENTS", 10)

    result = await server_module.handle_tool(
        "spawn_agents_parallel",
        {"agents": [{"prompt": "one"}, {"prompt": "two"}]},
    )
    payload = json.loads(result[0].text)

    assert len(payload) == 2
    assert max(starts) - min(starts) < 0.1


@pytest.mark.asyncio
async def test_timeout_handling_returns_error(mock_popen, mocker):
    process = mock_popen.return_value
    process.communicate.side_effect = TimeoutExpired(cmd="kimi", timeout=1)
    mocker.patch("moonbridge.server.os.killpg")
    process.wait.return_value = None

    result = await server_module.handle_tool(
        "spawn_agent",
        {"prompt": "Hello", "timeout_seconds": 30},
    )
    payload = json.loads(result[0].text)

    assert payload["status"] == "timeout"


@pytest.mark.asyncio
async def test_auth_detection_returns_actionable_message(mock_popen):
    process = mock_popen.return_value
    process.communicate.return_value = ("", "Authentication failed")
    process.returncode = 1

    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "auth_error"
    assert payload["message"] == "Run: kimi login"


@pytest.mark.asyncio
async def test_check_status_installed(mock_which_kimi, monkeypatch):
    monkeypatch.setattr(
        server_module,
        "_run_cli_sync",
        lambda *args, **kwargs: {
            "status": "success",
            "output": "ok",
            "stderr": None,
            "returncode": 0,
            "duration_ms": 1,
            "agent_index": 0,
        },
    )

    result = await server_module.handle_tool("check_status", {})
    payload = json.loads(result[0].text)

    assert payload["status"] == "success"


@pytest.mark.asyncio
async def test_check_status_not_installed(mock_which_no_kimi):
    result = await server_module.handle_tool("check_status", {})
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"


@pytest.mark.asyncio
async def test_max_agents_limit_enforced(monkeypatch):
    monkeypatch.setattr(server_module, "MAX_PARALLEL_AGENTS", 1)

    result = await server_module.handle_tool(
        "spawn_agents_parallel",
        {"agents": [{"prompt": "one"}, {"prompt": "two"}]},
    )
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"
    assert "Max" in payload["message"]


def test_validate_thinking_allowed():
    from moonbridge.adapters.kimi import KimiAdapter

    adapter = KimiAdapter()
    assert server_module._validate_thinking(adapter, True) is True
    assert server_module._validate_thinking(adapter, False) is False


def test_validate_thinking_not_supported(mocker):
    from moonbridge.adapters.base import AdapterConfig

    mock_adapter = mocker.Mock()
    mock_adapter.config = AdapterConfig(
        name="test",
        cli_command="test",
        tool_description="Test adapter",
        safe_env_keys=(),
        auth_patterns=(),
        auth_message="",
        install_hint="",
        supports_thinking=False,
    )
    with pytest.raises(ValueError, match="does not support thinking"):
        server_module._validate_thinking(mock_adapter, True)
    # False should pass even when not supported
    assert server_module._validate_thinking(mock_adapter, False) is False
