import importlib
import json
import logging
import os
import threading
import time
import gc
from collections.abc import Iterator
from subprocess import TimeoutExpired
from typing import Any
from unittest.mock import MagicMock, call

import pytest

server_module = importlib.import_module("moonbridge.server")


@pytest.mark.asyncio
async def test_spawn_agent_calls_kimi_cli(mock_popen: Any) -> None:
    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "success"
    args, _kwargs = mock_popen.call_args
    assert args[0] == ["kimi", "--print", "--prompt", "Hello"]
    assert "--thinking" not in args[0]


@pytest.mark.asyncio
async def test_spawn_agent_thinking_adds_flag(mock_popen: Any) -> None:
    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello", "thinking": True})
    payload = json.loads(result[0].text)

    assert payload["status"] == "success"
    args, _kwargs = mock_popen.call_args
    assert "--thinking" in args[0]


@pytest.mark.asyncio
async def test_spawn_agents_parallel_runs_concurrently(monkeypatch: Any) -> None:
    starts: list[float] = []
    ends: list[float] = []
    lock = threading.Lock()
    event = threading.Event()

    def fake_run(
        _adapter: Any,
        prompt: str,
        thinking: bool,
        cwd: str,
        timeout_seconds: int,
        agent_index: int,
    ) -> dict[str, Any]:
        with lock:
            starts.append(time.monotonic())
            if len(starts) == 2:
                event.set()
        event.wait(0.2)
        with lock:
            ends.append(time.monotonic())
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
    assert min(ends) >= max(starts)


@pytest.mark.asyncio
async def test_timeout_handling_returns_error(mock_popen: Any, mocker: Any) -> None:
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
@pytest.mark.parametrize(
    "exception, expected_stderr_part",
    [
        (FileNotFoundError, "CLI not found"),
        (PermissionError("no execute"), "Permission denied"),
        (OSError("boom"), "Failed to start process"),
    ],
)
async def test_popen_exceptions_return_error(
    mock_popen: Any, exception: Exception, expected_stderr_part: str
) -> None:
    mock_popen.side_effect = exception

    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"
    assert expected_stderr_part in payload["stderr"]
    assert payload["returncode"] == -1


@pytest.mark.asyncio
async def test_nonzero_exit_returns_error_status(mock_popen: Any) -> None:
    process = mock_popen.return_value
    process.communicate.return_value = ("ok", "some error")
    process.returncode = 2

    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"
    assert payload["stderr"] == "some error"
    assert payload["returncode"] == 2


@pytest.mark.asyncio
async def test_exception_during_communicate(mock_popen: Any, mocker: Any) -> None:
    process = mock_popen.return_value
    process.communicate.side_effect = RuntimeError("boom")
    process.wait.return_value = None
    mocker.patch("moonbridge.server.os.killpg")

    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"
    assert payload["stderr"] == "boom"
    assert payload["returncode"] == -1


@pytest.mark.asyncio
async def test_auth_detection_returns_actionable_message(mock_popen: Any) -> None:
    process = mock_popen.return_value
    process.communicate.return_value = ("", "Authentication failed")
    process.returncode = 1

    result = await server_module.handle_tool("spawn_agent", {"prompt": "Hello"})
    payload = json.loads(result[0].text)

    assert payload["status"] == "auth_error"
    assert payload["message"] == "Run: kimi login"


@pytest.mark.asyncio
async def test_check_status_installed(mock_which_kimi: Any, monkeypatch: Any) -> None:
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
async def test_check_status_not_installed(mock_which_no_kimi: Any) -> None:
    result = await server_module.handle_tool("check_status", {})
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"


@pytest.mark.asyncio
async def test_max_agents_limit_enforced(monkeypatch: Any) -> None:
    monkeypatch.setattr(server_module, "MAX_PARALLEL_AGENTS", 1)

    result = await server_module.handle_tool(
        "spawn_agents_parallel",
        {"agents": [{"prompt": "one"}, {"prompt": "two"}]},
    )
    payload = json.loads(result[0].text)

    assert payload["status"] == "error"
    assert "Max" in payload["message"]


def test_validate_thinking_allowed() -> None:
    from moonbridge.adapters.kimi import KimiAdapter

    adapter = KimiAdapter()
    assert server_module._validate_thinking(adapter, True) is True
    assert server_module._validate_thinking(adapter, False) is False


def test_validate_thinking_not_supported(mocker: Any) -> None:
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


def test_warn_if_unrestricted_emits_warning(
    monkeypatch: Any,
    capsys: Any,
    caplog: Any,
) -> None:
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


def test_warn_if_unrestricted_allows_none_allowed_dirs(
    monkeypatch: Any,
    capsys: Any,
    caplog: Any,
) -> None:
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


def test_warn_if_unrestricted_strict_exits(
    monkeypatch: Any,
    capsys: Any,
    caplog: Any,
    mocker: Any,
) -> None:
    monkeypatch.setattr(server_module.os, "getcwd", lambda: "/workdir")
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [])
    monkeypatch.setattr(server_module, "STRICT_MODE", True)
    exit_mock = mocker.patch("moonbridge.server.sys.exit")
    caplog.set_level(logging.ERROR, logger="moonbridge")

    server_module._warn_if_unrestricted()

    captured = capsys.readouterr()
    assert "(current: /workdir)" in captured.err
    exit_mock.assert_called_once_with(1)


def test_warn_if_unrestricted_no_warning_when_restricted(
    monkeypatch: Any,
    capsys: Any,
    caplog: Any,
) -> None:
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", ["/tmp"])
    caplog.set_level(logging.WARNING, logger="moonbridge")

    server_module._warn_if_unrestricted()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert not caplog.records


def test_validate_timeout_default(monkeypatch: Any) -> None:
    monkeypatch.setattr(server_module, "DEFAULT_TIMEOUT", 300)
    assert server_module._validate_timeout(None) == 300


def test_validate_timeout_valid_bounds() -> None:
    for value in (30, 600, 3600):
        assert server_module._validate_timeout(value) == value


def test_validate_timeout_too_low() -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be between 30 and 3600"):
        server_module._validate_timeout(29)


def test_validate_timeout_too_high() -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be between 30 and 3600"):
        server_module._validate_timeout(3601)


def test_validate_cwd_no_restrictions(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [])
    assert server_module._validate_cwd(str(tmp_path)) == os.path.realpath(tmp_path)


def test_validate_cwd_with_allowed_dirs(monkeypatch: Any, tmp_path: Any) -> None:
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    inside = allowed_dir / "inside"
    inside.mkdir()
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    assert server_module._validate_cwd(str(inside)) == os.path.realpath(inside)


def test_validate_cwd_rejects_outside(monkeypatch: Any, tmp_path: Any) -> None:
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    with pytest.raises(ValueError, match="cwd is not in MOONBRIDGE_ALLOWED_DIRS"):
        server_module._validate_cwd(str(outside))


def test_validate_cwd_subdirectory_allowed(monkeypatch: Any, tmp_path: Any) -> None:
    allowed_dir = tmp_path / "allowed"
    subdir = allowed_dir / "nested"
    subdir.mkdir(parents=True)
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    assert server_module._validate_cwd(str(subdir)) == os.path.realpath(subdir)


def test_validate_cwd_symlink_resolution(monkeypatch: Any, tmp_path: Any) -> None:
    allowed_dir = tmp_path / "allowed"
    target_dir = allowed_dir / "target"
    target_dir.mkdir(parents=True)
    symlink_path = tmp_path / "symlink"
    symlink_path.symlink_to(target_dir)
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    assert server_module._validate_cwd(str(symlink_path)) == os.path.realpath(symlink_path)


def test_validate_cwd_default_cwd(monkeypatch: Any, tmp_path: Any) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setattr(server_module.os, "getcwd", lambda: str(cwd))
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [])

    assert server_module._validate_cwd(None) == os.path.realpath(cwd)


def test_validate_prompt_empty_string() -> None:
    with pytest.raises(ValueError, match="prompt cannot be empty"):
        server_module._validate_prompt("")


def test_validate_prompt_whitespace_only() -> None:
    with pytest.raises(ValueError, match="prompt cannot be empty"):
        server_module._validate_prompt("   ")


def test_validate_prompt_valid() -> None:
    assert server_module._validate_prompt("test prompt") == "test prompt"


def test_validate_prompt_max_length() -> None:
    max_len = server_module.MAX_PROMPT_LENGTH
    prompt = "a" * max_len
    assert server_module._validate_prompt(prompt) == prompt


def test_validate_prompt_exceeds_max() -> None:
    max_len = server_module.MAX_PROMPT_LENGTH
    with pytest.raises(ValueError, match=f"prompt exceeds {max_len} characters"):
        server_module._validate_prompt("a" * (max_len + 1))


def test_validate_cwd_symlink_escape(monkeypatch: Any, tmp_path: Any) -> None:
    """Symlink inside allowed pointing outside should be rejected."""
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # Symlink inside allowed pointing to outside (escape attempt)
    symlink_inside = allowed_dir / "escape"
    symlink_inside.symlink_to(outside)
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    # Symlink resolves to outside, should be rejected
    with pytest.raises(ValueError, match="cwd is not in MOONBRIDGE_ALLOWED_DIRS"):
        server_module._validate_cwd(str(symlink_inside))


def test_validate_cwd_traversal_attempt(monkeypatch: Any, tmp_path: Any) -> None:
    """Path traversal via ../ should resolve before checking."""
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    # Attacker tries: /tmp/xxx/allowed/../outside
    traversal = str(allowed_dir / ".." / "outside")
    monkeypatch.setattr(server_module, "ALLOWED_DIRS", [str(allowed_dir)])

    with pytest.raises(ValueError, match="cwd is not in MOONBRIDGE_ALLOWED_DIRS"):
        server_module._validate_cwd(traversal)


@pytest.fixture
def reset_active_processes() -> Iterator[None]:
    server_module._active_processes.clear()
    yield
    server_module._active_processes.clear()


def test_track_process_adds_to_active_set(reset_active_processes: Any) -> None:
    proc = MagicMock()

    server_module._track_process(proc)

    assert any(ref() is proc for ref in server_module._active_processes)


def test_untrack_process_removes_from_set(reset_active_processes: Any) -> None:
    proc = MagicMock()
    server_module._track_process(proc)

    server_module._untrack_process(proc)

    assert not server_module._active_processes


def test_track_process_weakref_allows_gc(reset_active_processes: Any) -> None:
    proc = MagicMock()
    server_module._track_process(proc)

    del proc
    gc.collect()

    assert not server_module._active_processes


def test_terminate_process_sends_sigterm(mocker: Any) -> None:
    proc = MagicMock()
    proc.pid = 123
    mocker.patch.object(proc, "wait", return_value=None)
    killpg = mocker.patch("moonbridge.server.os.killpg")

    server_module._terminate_process(proc)

    killpg.assert_called_once_with(proc.pid, server_module.signal.SIGTERM)
    proc.wait.assert_called_once_with(timeout=5)


def test_terminate_process_escalates_to_sigkill(mocker: Any) -> None:
    proc = MagicMock()
    proc.pid = 456
    mocker.patch.object(
        proc,
        "wait",
        side_effect=[TimeoutExpired(cmd="kimi", timeout=5), None],
    )
    killpg = mocker.patch("moonbridge.server.os.killpg")

    server_module._terminate_process(proc)

    assert killpg.call_args_list == [
        call(proc.pid, server_module.signal.SIGTERM),
        call(proc.pid, server_module.signal.SIGKILL),
    ]
    assert proc.wait.call_count == 2


def test_terminate_process_handles_already_dead(mocker: Any) -> None:
    proc = MagicMock()
    proc.pid = 789
    mocker.patch.object(proc, "wait")
    killpg = mocker.patch(
        "moonbridge.server.os.killpg",
        side_effect=ProcessLookupError,
    )

    server_module._terminate_process(proc)

    killpg.assert_called_once_with(proc.pid, server_module.signal.SIGTERM)
    proc.wait.assert_not_called()


def test_cleanup_processes_terminates_running(
    mocker: Any, reset_active_processes: Any
) -> None:
    running = MagicMock()
    running.pid = 111
    running.poll.return_value = None
    finished = MagicMock()
    finished.pid = 222
    finished.poll.return_value = 0
    server_module._track_process(running)
    server_module._track_process(finished)
    terminate = mocker.patch("moonbridge.server._terminate_process")

    server_module._cleanup_processes()

    terminate.assert_called_once_with(running)


def test_cleanup_processes_clears_set(mocker: Any, reset_active_processes: Any) -> None:
    proc = MagicMock()
    proc.pid = 333
    proc.poll.return_value = None
    server_module._track_process(proc)
    mocker.patch("moonbridge.server._terminate_process")

    server_module._cleanup_processes()

    assert not server_module._active_processes
