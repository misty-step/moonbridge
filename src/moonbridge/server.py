"""MCP server for spawning Kimi K2.5 agents."""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import signal
import sys
import time
import weakref
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from moonbridge.adapters import ADAPTER_REGISTRY, CLIAdapter, get_adapter

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


def _run_cli_sync(
    adapter: CLIAdapter,
    prompt: str,
    thinking: bool,
    cwd: str,
    timeout_seconds: int,
    agent_index: int,
    model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
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
        return _result(
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
        if _auth_error(stderr_value, adapter):
            logger.info("Agent %s completed with status: auth_error", agent_index)
            return _result(
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
    if result["status"] == "auth_error":
        return {"status": "auth_error", "message": adapter.config.auth_message}
    if result["status"] == "success":
        return {
            "status": "success",
            "message": f"{adapter.config.name} CLI available and authenticated",
        }
    return {"status": "error", "message": f"{adapter.config.name} CLI error", "details": result}


def _adapter_info(cwd: str, adapter: CLIAdapter) -> dict[str, Any]:
    installed, _path = adapter.check_installed()
    authenticated = False
    if installed:
        timeout = min(DEFAULT_TIMEOUT, 60)
        result = _run_cli_sync(adapter, "status check", False, cwd, timeout, 0)
        authenticated = result["status"] == "success"
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
    parallel_desc = f"{tool_desc} Run multiple agents in parallel."
    status_desc = f"Verify {adapter.config.name} CLI is installed and authenticated"
    adapter_schema = {
        "type": "string",
        "enum": list(ADAPTER_REGISTRY.keys()),
        "description": "Backend to use (kimi, codex). Defaults to MOONBRIDGE_ADAPTER env or kimi.",
    }
    return [
        Tool(
            name="spawn_agent",
            description=tool_desc,
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Instructions for the agent (task, context, constraints)",
                    },
                    "adapter": adapter_schema,
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
                    "model": {
                        "type": "string",
                        "description": (
                            "Model to use (e.g., 'gpt-5.2-codex', 'kimi-k2.5'). "
                            "Falls back to MOONBRIDGE_{ADAPTER}_MODEL or MOONBRIDGE_MODEL env vars."
                        ),
                    },
                    "reasoning_effort": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "xhigh"],
                        "description": (
                            "Reasoning effort for Codex (low, medium, high, xhigh). "
                            "Ignored for Kimi (use thinking instead)."
                        ),
                    },
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="spawn_agents_parallel",
            description=parallel_desc,
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
                                "adapter": adapter_schema,
                                "thinking": {"type": "boolean", "default": False},
                                "timeout_seconds": {
                                    "type": "integer",
                                    "description": "Max execution time (30-3600s)",
                                    "default": DEFAULT_TIMEOUT,
                                    "minimum": 30,
                                    "maximum": 3600,
                                },
                                "model": {
                                    "type": "string",
                                    "description": (
                                        "Model to use. Falls back to "
                                        "MOONBRIDGE_{ADAPTER}_MODEL or MOONBRIDGE_MODEL env vars."
                                    ),
                                },
                                "reasoning_effort": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high", "xhigh"],
                                    "description": (
                                        "Reasoning effort for Codex (low, medium, high, xhigh). "
                                        "Ignored for Kimi."
                                    ),
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
            name="list_adapters",
            description="List available adapters and their status",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="check_status",
            description=status_desc,
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls. Exposed for testing."""
    try:
        cwd = _validate_cwd(None)
        if name == "spawn_agent":
            adapter = get_adapter(arguments.get("adapter"))
            prompt = _validate_prompt(arguments["prompt"])
            thinking = _validate_thinking(adapter, bool(arguments.get("thinking", False)))
            timeout_seconds = _validate_timeout(arguments.get("timeout_seconds"))
            model = _resolve_model(adapter, arguments.get("model"))
            reasoning_effort = arguments.get("reasoning_effort")
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(
                    None,
                    _run_cli_sync,
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
                adapter = get_adapter(spec.get("adapter"))
                prompt = _validate_prompt(spec["prompt"])
                thinking = _validate_thinking(adapter, bool(spec.get("thinking", False)))
                model = _resolve_model(adapter, spec.get("model"))
                reasoning_effort = spec.get("reasoning_effort")
                tasks.append(
                    loop.run_in_executor(
                        None,
                        _run_cli_sync,
                        adapter,
                        prompt,
                        thinking,
                        cwd,
                        _validate_timeout(spec.get("timeout_seconds")),
                        idx,
                        model,
                        reasoning_effort,
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
