"""MCP server for spawning Kimi K2.5 agents."""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import shutil
import signal
import sys
import time
import weakref
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("moonbridge")

logger = logging.getLogger("moonbridge")

SAFE_ENV_KEYS = [
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "TERM",
    "SHELL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "LC_ALL",
    "LC_CTYPE",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "KIMI_CONFIG_PATH",
]
AUTH_PATTERNS = ["login required", "unauthorized", "authentication failed", "401", "403"]

DEFAULT_TIMEOUT = int(os.environ.get("MOONBRIDGE_TIMEOUT", "600"))
MAX_PARALLEL_AGENTS = int(os.environ.get("MOONBRIDGE_MAX_AGENTS", "10"))
_ALLOWED_DIRS_ENV = os.environ.get("MOONBRIDGE_ALLOWED_DIRS")
ALLOWED_DIRS = [
    os.path.realpath(path)
    for path in (_ALLOWED_DIRS_ENV.split(os.pathsep) if _ALLOWED_DIRS_ENV else [])
    if path
]
MAX_PROMPT_LENGTH = 100_000

_active_processes: set[weakref.ref[Popen[str]]] = set()


def _configure_logging() -> None:
    level = os.environ.get("MOONBRIDGE_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _safe_env() -> dict[str, str]:
    return {key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ}


def _validate_timeout(timeout_seconds: int | None) -> int:
    value = DEFAULT_TIMEOUT if timeout_seconds is None else int(timeout_seconds)
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


def _build_command(prompt: str, thinking: bool) -> list[str]:
    cmd = ["kimi", "--print"]
    if thinking:
        cmd.append("--thinking")
    cmd.extend(["--prompt", prompt])
    return cmd


def _terminate_process(proc: Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
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


def _auth_error(stderr: str | None) -> bool:
    if not stderr:
        return False
    lowered = stderr.lower()
    return any(pattern in lowered for pattern in AUTH_PATTERNS)


def _result(
    *,
    status: str,
    output: str,
    stderr: str | None,
    returncode: int,
    duration_ms: int,
    agent_index: int,
    message: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "output": output,
        "stderr": stderr,
        "returncode": returncode,
        "duration_ms": duration_ms,
        "agent_index": agent_index,
    }
    if message is not None:
        payload["message"] = message
    return payload


def _run_kimi_sync(
    prompt: str,
    thinking: bool,
    cwd: str,
    timeout_seconds: int,
    agent_index: int,
) -> dict[str, Any]:
    start = time.monotonic()
    cmd = _build_command(prompt, thinking)
    logger.debug("Spawning agent with prompt: %s...", prompt[:100])
    try:
        proc = Popen(
            cmd,
            stdout=PIPE,
            stderr=PIPE,
            text=True,
            cwd=cwd,
            env=_safe_env(),
            start_new_session=True,
        )
    except FileNotFoundError:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Kimi CLI not found or not executable")
        return _result(
            status="error",
            output="",
            stderr="kimi CLI not found or not executable",
            returncode=-1,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )
    except PermissionError as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("Permission denied starting process: %s", exc)
        return _result(
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
        return _result(
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
        if _auth_error(stderr_value):
            logger.info("Agent %s completed with status: auth_error", agent_index)
            return _result(
                status="auth_error",
                output=stdout,
                stderr=stderr_value,
                returncode=proc.returncode,
                duration_ms=duration_ms,
                agent_index=agent_index,
                message="Run: kimi login",
            )
        status = "success" if proc.returncode == 0 else "error"
        logger.info("Agent %s completed with status: %s", agent_index, status)
        return _result(
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
        return _result(
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
        return _result(
            status="error",
            output="",
            stderr=str(exc),
            returncode=-1,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )
    finally:
        _untrack_process(proc)


def _json_text(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=True))]


def _status_check(cwd: str) -> dict[str, Any]:
    if not shutil.which("kimi"):
        return {"status": "error", "message": "Kimi CLI not found. Install: uv tool install kimi-cli"}  # noqa: E501
    timeout = min(DEFAULT_TIMEOUT, 60)
    result = _run_kimi_sync("status check", False, cwd, timeout, 0)
    if result["status"] == "auth_error":
        return {"status": "auth_error", "message": "Run: kimi login"}
    if result["status"] == "success":
        return {"status": "success", "message": "Kimi CLI available and authenticated"}
    return {"status": "error", "message": "Kimi CLI error", "details": result}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="spawn_agent",
            description=(
                "Spawn a Kimi K2.5 agent in the current directory. "
                "Kimi excels at frontend development and visual coding."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Instructions for the agent (task, context, constraints)",
                    },
                    "thinking": {
                        "type": "boolean",
                        "description": "Enable extended reasoning mode for complex tasks",
                        "default": False,
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Max execution time (30-3600s)",
                        "default": DEFAULT_TIMEOUT,
                        "minimum": 30,
                        "maximum": 3600,
                    },
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="spawn_agents_parallel",
            description=(
                "Spawn multiple Kimi K2.5 agents in parallel. "
                "Each agent runs independently in the current working directory."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agents": {
                        "type": "array",
                        "description": "List of agent specs with prompt and optional settings",
                        "items": {
                            "type": "object",
                            "properties": {
                                "prompt": {"type": "string"},
                                "thinking": {"type": "boolean", "default": False},
                                "timeout_seconds": {
                                    "type": "integer",
                                    "description": "Max execution time (30-3600s)",
                                    "default": DEFAULT_TIMEOUT,
                                    "minimum": 30,
                                    "maximum": 3600,
                                },
                            },
                            "required": ["prompt"],
                        },
                    },
                },
                "required": ["agents"],
            },
        ),
        Tool(
            name="check_status",
            description="Verify Kimi CLI is installed and authenticated",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls. Exposed for testing."""
    try:
        cwd = _validate_cwd(None)
        if name == "spawn_agent":
            prompt = _validate_prompt(arguments["prompt"])
            thinking = bool(arguments.get("thinking", False))
            timeout_seconds = _validate_timeout(arguments.get("timeout_seconds"))
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(
                    None,
                    _run_kimi_sync,
                    prompt,
                    thinking,
                    cwd,
                    timeout_seconds,
                    0,
                )
            except asyncio.CancelledError:
                return _json_text(
                    _result(
                        status="cancelled",
                        output="",
                        stderr=None,
                        returncode=-1,
                        duration_ms=0,
                        agent_index=0,
                    )
                )
            return _json_text(result)

        if name == "spawn_agents_parallel":
            agents = list(arguments["agents"])
            if len(agents) > MAX_PARALLEL_AGENTS:
                raise ValueError(f"Max {MAX_PARALLEL_AGENTS} agents allowed")
            loop = asyncio.get_running_loop()
            tasks = []
            for idx, spec in enumerate(agents):
                prompt = _validate_prompt(spec["prompt"])
                tasks.append(
                    loop.run_in_executor(
                        None,
                        _run_kimi_sync,
                        prompt,
                        bool(spec.get("thinking", False)),
                        cwd,
                        _validate_timeout(spec.get("timeout_seconds")),
                        idx,
                    )
                )
            try:
                results = await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                cancelled = [
                    _result(
                        status="cancelled",
                        output="",
                        stderr=None,
                        returncode=-1,
                        duration_ms=0,
                        agent_index=idx,
                    )
                    for idx in range(len(agents))
                ]
                return _json_text(cancelled)
            results.sort(key=lambda item: item["agent_index"])
            return _json_text(results)

        if name == "check_status":
            return _json_text(_status_check(cwd))

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
    if not shutil.which("kimi"):
        print(
            "Error: Kimi CLI not found. Install: uv tool install kimi-cli",
            file=sys.stderr,
        )
        sys.exit(1)
    asyncio.run(run())


if __name__ == "__main__":
    main()
