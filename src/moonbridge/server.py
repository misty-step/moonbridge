"""MCP server for spawning AI coding agents."""

from __future__ import annotations

import asyncio
import atexit
import difflib
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import time
import weakref
from dataclasses import replace
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from moonbridge.adapters import ADAPTER_REGISTRY, CLIAdapter, get_adapter
from moonbridge.adapters.base import AgentResult
from moonbridge.tools import build_tools

server = Server("moonbridge")

logger = logging.getLogger("moonbridge")

DEFAULT_TIMEOUT = int(os.environ.get("MOONBRIDGE_TIMEOUT", "600"))
MAX_PARALLEL_AGENTS = int(os.environ.get("MOONBRIDGE_MAX_AGENTS", "10"))
STRICT_MODE = os.environ.get("MOONBRIDGE_STRICT", "").strip().lower() in {"1", "true"}
_ALLOWED_DIRS_ENV = os.environ.get("MOONBRIDGE_ALLOWED_DIRS")
ALLOWED_DIRS = [
    os.path.realpath(path)
    for path in (_ALLOWED_DIRS_ENV.split(os.pathsep) if _ALLOWED_DIRS_ENV else [])
    if path
]
MAX_PROMPT_LENGTH = 100_000
_SANDBOX_ENV = os.environ.get("MOONBRIDGE_SANDBOX", "").strip().lower()
SANDBOX_MODE = _SANDBOX_ENV in {"1", "true", "yes", "copy"}
SANDBOX_KEEP = os.environ.get("MOONBRIDGE_SANDBOX_KEEP", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
SANDBOX_MAX_DIFF_BYTES = int(os.environ.get("MOONBRIDGE_SANDBOX_MAX_DIFF", "500000"))
SANDBOX_IGNORE_DIRS = {
    ".git",
    ".venv",
    ".tox",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}
SANDBOX_IGNORE_FILES = {".DS_Store"}

_active_processes: set[weakref.ref[Popen[str]]] = set()


def _configure_logging() -> None:
    level = os.environ.get("MOONBRIDGE_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _warn_if_unrestricted() -> None:
    if ALLOWED_DIRS:
        return
    current = os.getcwd()
    message = (
        "MOONBRIDGE_ALLOWED_DIRS is not set. Agents can operate in any directory. "
        f"Set MOONBRIDGE_ALLOWED_DIRS=/path1{os.pathsep}/path2 to restrict. "
        f"(current: {current})"
    )
    if STRICT_MODE:
        logger.error(message)
        print(message, file=sys.stderr)
        sys.exit(1)
        return
    logger.warning(message)
    print(message, file=sys.stderr)


def _safe_env(adapter: CLIAdapter) -> dict[str, str]:
    env = {key: os.environ[key] for key in adapter.config.safe_env_keys if key in os.environ}
    if "PATH" not in env and "PATH" in os.environ:
        env["PATH"] = os.environ["PATH"]
    return env


def _resolve_timeout(adapter: CLIAdapter, timeout_seconds: int | None) -> int:
    """Resolve timeout: explicit > adapter-env > adapter-default > global."""
    if timeout_seconds is not None:
        value = int(timeout_seconds)
    else:
        # Check adapter-specific env var first
        env_key = f"MOONBRIDGE_{adapter.config.name.upper()}_TIMEOUT"
        if env_val := os.environ.get(env_key):
            value = int(env_val)
        elif adapter.config.default_timeout != 600:
            # Use adapter default if explicitly set (not the base default)
            value = adapter.config.default_timeout
        else:
            value = DEFAULT_TIMEOUT
    if value < 30 or value > 3600:
        raise ValueError("timeout_seconds must be between 30 and 3600")
    return value


def _validate_cwd(cwd: str | None) -> str:
    resolved = os.path.realpath(cwd or os.getcwd())
    if not ALLOWED_DIRS:
        return resolved
    for allowed in ALLOWED_DIRS:
        allowed_real = os.path.realpath(allowed)
        if os.path.commonpath([resolved, allowed_real]) == allowed_real:
            return resolved
    raise ValueError("cwd is not in MOONBRIDGE_ALLOWED_DIRS")


def _validate_prompt(prompt: str) -> str:
    if not prompt or not prompt.strip():
        raise ValueError("prompt cannot be empty")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise ValueError(f"prompt exceeds {MAX_PROMPT_LENGTH} characters")
    return prompt


def _validate_thinking(adapter: CLIAdapter, thinking: bool) -> bool:
    """Validate thinking flag against adapter capability."""
    if thinking and not adapter.config.supports_thinking:
        raise ValueError(f"{adapter.config.name} adapter does not support thinking mode")
    return thinking


def _validate_model(model: str | None) -> str | None:
    """Validate and normalize model string.

    - Strips whitespace
    - Returns None for empty/whitespace-only strings
    - Rejects models starting with '-' (flag injection prevention)
    """
    if not model:
        return None
    model = model.strip()
    if not model:
        return None
    if model.startswith("-"):
        raise ValueError(f"model cannot start with '-': {model}")
    return model


def _resolve_model(adapter: CLIAdapter, model_param: str | None) -> str | None:
    """Resolve model: param > adapter env > global env > None.

    All values are validated and normalized.
    """
    if validated := _validate_model(model_param):
        return validated
    adapter_env = f"MOONBRIDGE_{adapter.config.name.upper()}_MODEL"
    if validated := _validate_model(os.environ.get(adapter_env)):
        return validated
    return _validate_model(os.environ.get("MOONBRIDGE_MODEL"))


def _is_ignored_dir(name: str) -> bool:
    return name in SANDBOX_IGNORE_DIRS


def _is_ignored_file(name: str) -> bool:
    if name in SANDBOX_IGNORE_FILES:
        return True
    return name.endswith((".pyc", ".pyo"))


def _collect_files(root: str) -> set[str]:
    files: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]
        rel_dir = os.path.relpath(dirpath, root)
        for filename in filenames:
            if _is_ignored_file(filename):
                continue
            rel_path = filename if rel_dir == "." else os.path.join(rel_dir, filename)
            files.add(rel_path)
    return files


def _read_text(path: str) -> str | None:
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _diff_trees(
    original: str,
    sandbox: str,
    max_bytes: int,
) -> tuple[str, dict[str, int], bool]:
    original_files = _collect_files(original)
    sandbox_files = _collect_files(sandbox)
    all_files = sorted(original_files | sandbox_files)
    diff_chunks: list[str] = []
    size = 0
    truncated = False
    summary = {"added": 0, "modified": 0, "deleted": 0, "binary": 0}

    def append_chunk(chunk: str) -> None:
        nonlocal size, truncated
        if truncated or not chunk:
            return
        remaining = max_bytes - size
        if remaining <= 0:
            truncated = True
            return
        if len(chunk) > remaining:
            diff_chunks.append(chunk[:remaining])
            truncated = True
            size = max_bytes
            return
        diff_chunks.append(chunk)
        size += len(chunk)

    for rel_path in all_files:
        original_path = os.path.join(original, rel_path)
        sandbox_path = os.path.join(sandbox, rel_path)
        original_exists = os.path.exists(original_path)
        sandbox_exists = os.path.exists(sandbox_path)

        if not original_exists and sandbox_exists:
            summary["added"] += 1
            sandbox_text = _read_text(sandbox_path)
            if sandbox_text is None:
                summary["binary"] += 1
                append_chunk(f"Binary files /dev/null and b/{rel_path} differ\n")
                continue
            diff = difflib.unified_diff(
                [],
                sandbox_text.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=f"b/{rel_path}",
            )
            append_chunk("".join(diff))
            continue

        if original_exists and not sandbox_exists:
            summary["deleted"] += 1
            original_text = _read_text(original_path)
            if original_text is None:
                summary["binary"] += 1
                append_chunk(f"Binary files a/{rel_path} and /dev/null differ\n")
                continue
            diff = difflib.unified_diff(
                original_text.splitlines(keepends=True),
                [],
                fromfile=f"a/{rel_path}",
                tofile="/dev/null",
            )
            append_chunk("".join(diff))
            continue

        if not original_exists or not sandbox_exists:
            continue

        original_bytes = Path(original_path).read_bytes()
        sandbox_bytes = Path(sandbox_path).read_bytes()
        if original_bytes == sandbox_bytes:
            continue

        original_text = None
        sandbox_text = None
        try:
            original_text = original_bytes.decode("utf-8")
            sandbox_text = sandbox_bytes.decode("utf-8")
        except UnicodeDecodeError:
            summary["binary"] += 1
            append_chunk(f"Binary files a/{rel_path} and b/{rel_path} differ\n")
            continue

        summary["modified"] += 1
        diff = difflib.unified_diff(
            original_text.splitlines(keepends=True),
            sandbox_text.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
        append_chunk("".join(diff))

    if truncated and size < max_bytes:
        note = "\n... diff truncated ...\n"
        diff_chunks.append(note[: max_bytes - size])
    return ("".join(diff_chunks), summary, truncated)


def _terminate_process(proc: Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            proc.poll()  # Reap the process that died between SIGTERM and SIGKILL
            return
        proc.wait(timeout=5)


def _cleanup_processes() -> None:
    for ref in list(_active_processes):
        proc = ref()
        if proc and proc.poll() is None:
            logger.debug("Cleaning up orphan process %s", proc.pid)
            _terminate_process(proc)
    _active_processes.clear()


atexit.register(_cleanup_processes)


def _track_process(proc: Popen[str]) -> None:
    _active_processes.add(weakref.ref(proc, lambda ref: _active_processes.discard(ref)))


def _untrack_process(proc: Popen[str]) -> None:
    for ref in list(_active_processes):
        if ref() is proc:
            _active_processes.discard(ref)
            break


def _auth_error(stderr: str | None, adapter: CLIAdapter) -> bool:
    if not stderr:
        return False
    lowered = stderr.lower()
    return any(pattern in lowered for pattern in adapter.config.auth_patterns)


def _run_cli_sandboxed(
    adapter: CLIAdapter,
    prompt: str,
    thinking: bool,
    cwd: str,
    timeout_seconds: int,
    agent_index: int,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> AgentResult:
    sandbox_root = tempfile.mkdtemp(prefix="moonbridge-sandbox-")
    sandbox_cwd = os.path.join(sandbox_root, "workspace")
    try:
        shutil.copytree(
            cwd,
            sandbox_cwd,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                *SANDBOX_IGNORE_DIRS,
                *SANDBOX_IGNORE_FILES,
                "*.pyc",
                "*.pyo",
            ),
        )
        result = _run_cli_sync(
            adapter,
            prompt,
            thinking,
            sandbox_cwd,
            timeout_seconds,
            agent_index,
            model,
            reasoning_effort,
        )
        try:
            diff, summary, truncated = _diff_trees(cwd, sandbox_cwd, SANDBOX_MAX_DIFF_BYTES)
            sandbox_payload: dict[str, Any] = {
                "enabled": True,
                "summary": summary,
                "diff": diff,
                "truncated": truncated,
            }
        except Exception as exc:
            sandbox_payload = {"enabled": True, "error": str(exc)}
        if SANDBOX_KEEP:
            sandbox_payload["path"] = sandbox_root
        raw = dict(result.raw or {})
        raw["sandbox"] = sandbox_payload
        return replace(result, raw=raw)
    except Exception as exc:
        return AgentResult(
            status="error",
            output="",
            stderr=f"sandbox error: {exc}",
            returncode=-1,
            duration_ms=0,
            agent_index=agent_index,
        )
    finally:
        if not SANDBOX_KEEP:
            shutil.rmtree(sandbox_root, ignore_errors=True)


def _run_cli_sync(
    adapter: CLIAdapter,
    prompt: str,
    thinking: bool,
    cwd: str,
    timeout_seconds: int,
    agent_index: int,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> AgentResult:
    start = time.monotonic()
    cmd = adapter.build_command(prompt, thinking, model, reasoning_effort)
    logger.debug("Spawning agent with prompt: %s...", prompt[:100])
    try:
        proc = Popen(
            cmd,
            stdout=PIPE,
            stderr=PIPE,
            text=True,
            cwd=cwd,
            env=_safe_env(adapter),
            start_new_session=True,
        )
    except FileNotFoundError:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("%s CLI not found or not executable", adapter.config.name)
        return AgentResult(
            status="error",
            output="",
            stderr=f"{adapter.config.name} CLI not found or not executable",
            returncode=-1,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )
    except PermissionError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Permission denied starting process: %s", exc)
        return AgentResult(
            status="error",
            output="",
            stderr=f"Permission denied: {exc}",
            returncode=-1,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Failed to start process: %s", exc)
        return AgentResult(
            status="error",
            output="",
            stderr=f"Failed to start process: {exc}",
            returncode=-1,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )
    _track_process(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        duration_ms = int((time.monotonic() - start) * 1000)
        stderr_value = stderr or None
        if _auth_error(stderr_value, adapter):
            logger.info("Agent %s completed with status: auth_error", agent_index)
            return AgentResult(
                status="auth_error",
                output=stdout,
                stderr=stderr_value,
                returncode=proc.returncode,
                duration_ms=duration_ms,
                agent_index=agent_index,
                message=adapter.config.auth_message,
            )
        status = "success" if proc.returncode == 0 else "error"
        logger.info("Agent %s completed with status: %s", agent_index, status)
        return AgentResult(
            status=status,
            output=stdout,
            stderr=stderr_value,
            returncode=proc.returncode,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )
    except TimeoutExpired:
        _terminate_process(proc)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.warning("Agent %s timed out after %s seconds", agent_index, timeout_seconds)
        return AgentResult(
            status="timeout",
            output="",
            stderr=None,
            returncode=-1,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )
    except Exception as exc:
        _terminate_process(proc)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Agent %s failed with error: %s", agent_index, exc)
        return AgentResult(
            status="error",
            output="",
            stderr=str(exc),
            returncode=-1,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )
    finally:
        _untrack_process(proc)


def _run_cli(
    adapter: CLIAdapter,
    prompt: str,
    thinking: bool,
    cwd: str,
    timeout_seconds: int,
    agent_index: int,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> AgentResult:
    if SANDBOX_MODE:
        return _run_cli_sandboxed(
            adapter,
            prompt,
            thinking,
            cwd,
            timeout_seconds,
            agent_index,
            model,
            reasoning_effort,
        )
    return _run_cli_sync(
        adapter,
        prompt,
        thinking,
        cwd,
        timeout_seconds,
        agent_index,
        model,
        reasoning_effort,
    )


def _json_text(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=True))]


def _status_check(cwd: str, adapter: CLIAdapter) -> dict[str, Any]:
    installed, _path = adapter.check_installed()
    if not installed:
        return {
            "status": "error",
            "message": (
                f"{adapter.config.name} CLI not found. Install: {adapter.config.install_hint}"
            ),
        }
    timeout = min(DEFAULT_TIMEOUT, 60)
    result = _run_cli_sync(adapter, "status check", False, cwd, timeout, 0)
    if result.status == "auth_error":
        return {"status": "auth_error", "message": adapter.config.auth_message}
    if result.status == "success":
        return {
            "status": "success",
            "message": f"{adapter.config.name} CLI available and authenticated",
        }
    return {
        "status": "error",
        "message": f"{adapter.config.name} CLI error",
        "details": result.to_dict(),
    }


def _adapter_info(cwd: str, adapter: CLIAdapter) -> dict[str, Any]:
    installed, _path = adapter.check_installed()
    authenticated = False
    if installed:
        timeout = min(DEFAULT_TIMEOUT, 60)
        result = _run_cli_sync(adapter, "status check", False, cwd, timeout, 0)
        authenticated = result.status == "success"
    return {
        "name": adapter.config.name,
        "description": adapter.config.tool_description,
        "supports_thinking": adapter.config.supports_thinking,
        "known_models": adapter.config.known_models,
        "installed": installed,
        "authenticated": authenticated,
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    adapter = get_adapter()
    tool_desc = adapter.config.tool_description
    status_desc = f"Verify {adapter.config.name} CLI is installed and authenticated"
    return build_tools(
        adapter_names=tuple(ADAPTER_REGISTRY.keys()),
        default_timeout=DEFAULT_TIMEOUT,
        tool_description=tool_desc,
        status_description=status_desc,
    )


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls. Exposed for testing."""
    try:
        cwd = _validate_cwd(None)
        if name == "spawn_agent":
            adapter = get_adapter(arguments.get("adapter"))
            prompt = _validate_prompt(arguments["prompt"])
            thinking = _validate_thinking(adapter, bool(arguments.get("thinking", False)))
            timeout_seconds = _resolve_timeout(adapter, arguments.get("timeout_seconds"))
            model = _resolve_model(adapter, arguments.get("model"))
            reasoning_effort = arguments.get("reasoning_effort")
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(
                    None,
                    _run_cli,
                    adapter,
                    prompt,
                    thinking,
                    cwd,
                    timeout_seconds,
                    0,
                    model,
                    reasoning_effort,
                )
            except asyncio.CancelledError:
                return _json_text(
                    AgentResult(
                        status="cancelled",
                        output="",
                        stderr=None,
                        returncode=-1,
                        duration_ms=0,
                        agent_index=0,
                    ).to_dict()
                )
            return _json_text(result.to_dict())

        if name == "spawn_agents_parallel":
            agents = list(arguments["agents"])
            if len(agents) > MAX_PARALLEL_AGENTS:
                raise ValueError(f"Max {MAX_PARALLEL_AGENTS} agents allowed")
            loop = asyncio.get_running_loop()
            tasks = []
            for idx, spec in enumerate(agents):
                adapter = get_adapter(spec.get("adapter"))
                prompt = _validate_prompt(spec["prompt"])
                thinking = _validate_thinking(adapter, bool(spec.get("thinking", False)))
                model = _resolve_model(adapter, spec.get("model"))
                reasoning_effort = spec.get("reasoning_effort")
                tasks.append(
                    loop.run_in_executor(
                        None,
                        _run_cli,
                        adapter,
                        prompt,
                        thinking,
                        cwd,
                        _resolve_timeout(adapter, spec.get("timeout_seconds")),
                        idx,
                        model,
                        reasoning_effort,
                    )
                )
            try:
                results = await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                cancelled = [
                    AgentResult(
                        status="cancelled",
                        output="",
                        stderr=None,
                        returncode=-1,
                        duration_ms=0,
                        agent_index=idx,
                    )
                    for idx in range(len(agents))
                ]
                return _json_text([item.to_dict() for item in cancelled])
            results.sort(key=lambda item: item.agent_index)
            return _json_text([item.to_dict() for item in results])

        if name == "list_adapters":
            info = [_adapter_info(cwd, adapter) for adapter in ADAPTER_REGISTRY.values()]
            return _json_text(info)

        if name == "check_status":
            adapter = get_adapter()
            return _json_text(_status_check(cwd, adapter))

        return _json_text({"status": "error", "message": f"Unknown tool: {name}"})
    except ValueError as exc:
        logger.warning("Validation error: %s", exc)
        return _json_text({"status": "error", "message": str(exc)})
    except Exception as exc:
        logger.error("Unhandled error: %s", exc)
        return _json_text({"status": "error", "message": str(exc)})


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """MCP tool handler - delegates to handle_tool."""
    return await handle_tool(name, arguments)


async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    _configure_logging()
    _warn_if_unrestricted()
    from moonbridge import __version__
    from moonbridge.version_check import check_for_updates

    check_for_updates(__version__)
    adapter = get_adapter()
    installed, _path = adapter.check_installed()
    if not installed:
        print(
            f"Error: {adapter.config.name} CLI not found. Install: {adapter.config.install_hint}",
            file=sys.stderr,
        )
        sys.exit(1)
    asyncio.run(run())


if __name__ == "__main__":
    main()
