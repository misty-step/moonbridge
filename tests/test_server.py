import importlib
import json
import logging
import os
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


def test_warn_if_unrestricted_emits_warning(monkeypatch, capsys, caplog):
    monkeypatch.setattr(server_module.os, "getcwd", lambda: "/workdir")
    message = (
        "MOONBRIDGE_ALLOWED_DIRS is not set. Agents can operate in any directory. "
        f"Set MOONBRIDGE_ALLOWED_DIRS=/path1{server_module.os.pathsep}/path2 to restrict. "
        "(current: /workdir)"
    )
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [])
    caplog.set_level(logging.WARNING, logger="moonbridge")

    server_module._warn_if_unrestricted()

    captured = capsys.readouterr()
    assert message in captured.err
    assert any(
        record.levelno == logging.WARNING and record.message == message for record in caplog.records
    )


def test_warn_if_unrestricted_allows_none_allowed_dirs(monkeypatch, capsys, caplog):
    monkeypatch.setattr(server_module.os, "getcwd", lambda: "/workdir")
    message = (
        "MOONBRIDGE_ALLOWED_DIRS is not set. Agents can operate in any directory. "
        f"Set MOONBRIDGE_ALLOWED_DIRS=/path1{server_module.os.pathsep}/path2 to restrict. "
        "(current: /workdir)"
    )
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", None)
    caplog.set_level(logging.WARNING, logger="moonbridge")

    server_module._warn_if_unrestricted()

    captured = capsys.readouterr()
    assert message in captured.err
    assert any(
        record.levelno == logging.WARNING and record.message == message for record in caplog.records
    )


def test_warn_if_unrestricted_strict_exits(monkeypatch, capsys, caplog, mocker):
    monkeypatch.setattr(server_module.os, "getcwd", lambda: "/workdir")
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [])
    monkeypatch.setattr(server_module, "STRICT_MODE", True)
    exit_mock = mocker.patch("moonbridge.server.sys.exit")
    caplog.set_level(logging.ERROR, logger="moonbridge")

    server_module._warn_if_unrestricted()

    captured = capsys.readouterr()
    assert "(current: /workdir)" in captured.err
    exit_mock.assert_called_once_with(1)


def test_warn_if_unrestricted_no_warning_when_restricted(monkeypatch, capsys, caplog):
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", ["/tmp"])
    caplog.set_level(logging.WARNING, logger="moonbridge")

    server_module._warn_if_unrestricted()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert not caplog.records


def test_validate_timeout_default(monkeypatch):
    monkeypatch.setattr(server_module, "DEFAULT_TIMEOUT", 300)
    assert server_module._validate_timeout(None) == 300


def test_validate_timeout_valid_bounds():
    for value in (30, 600, 3600):
        assert server_module._validate_timeout(value) == value


def test_validate_timeout_too_low():
    with pytest.raises(ValueError, match="timeout_seconds must be between 30 and 3600"):
        server_module._validate_timeout(29)


def test_validate_timeout_too_high():
    with pytest.raises(ValueError, match="timeout_seconds must be between 30 and 3600"):
        server_module._validate_timeout(3601)


def test_validate_cwd_no_restrictions(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [])
    assert server_module._validate_cwd(str(tmp_path)) == os.path.realpath(tmp_path)


def test_validate_cwd_with_allowed_dirs(monkeypatch, tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    inside = allowed_dir / "inside"
    inside.mkdir()
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    assert server_module._validate_cwd(str(inside)) == os.path.realpath(inside)


def test_validate_cwd_rejects_outside(monkeypatch, tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    with pytest.raises(ValueError, match="cwd is not in MOONBRIDGE_ALLOWED_DIRS"):
        server_module._validate_cwd(str(outside))


def test_validate_cwd_subdirectory_allowed(monkeypatch, tmp_path):
    allowed_dir = tmp_path / "allowed"
    subdir = allowed_dir / "nested"
    subdir.mkdir(parents=True)
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    assert server_module._validate_cwd(str(subdir)) == os.path.realpath(subdir)


def test_validate_cwd_symlink_resolution(monkeypatch, tmp_path):
    allowed_dir = tmp_path / "allowed"
    target_dir = allowed_dir / "target"
    target_dir.mkdir(parents=True)
    symlink_path = tmp_path / "symlink"
    symlink_path.symlink_to(target_dir)
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    assert server_module._validate_cwd(str(symlink_path)) == os.path.realpath(symlink_path)


def test_validate_cwd_default_cwd(monkeypatch, tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(server_module.os, "getcwd", lambda: str(cwd))
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [])

    assert server_module._validate_cwd(None) == os.path.realpath(cwd)


def test_validate_prompt_empty_string():
    with pytest.raises(ValueError, match="prompt cannot be empty"):
        server_module._validate_prompt("")


def test_validate_prompt_whitespace_only():
    with pytest.raises(ValueError, match="prompt cannot be empty"):
        server_module._validate_prompt("   ")


def test_validate_prompt_valid():
    assert server_module._validate_prompt("test prompt") == "test prompt"


def test_validate_prompt_max_length():
    max_len = server_module.MAX_PROMPT_LENGTH
    prompt = "a" * max_len
    assert server_module._validate_prompt(prompt) == prompt


def test_validate_prompt_exceeds_max():
    max_len = server_module.MAX_PROMPT_LENGTH
    with pytest.raises(ValueError, match=f"prompt exceeds {max_len} characters"):
        server_module._validate_prompt("a" * (max_len + 1))
