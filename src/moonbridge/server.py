"""MCP server for spawning AI coding agents."""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import signal
import sys
import time
import weakref
from dataclasses import replace
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from moonbridge import tool_handlers
from moonbridge.adapters import ADAPTER_REGISTRY, CLIAdapter, get_adapter
from moonbridge.adapters.base import AgentResult
from moonbridge.signals import extract_quality_signals
from moonbridge.telemetry import trace_span
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
_TIMEOUT_TAIL_CHARS = 10_000
MAX_OUTPUT_CHARS = int(os.environ.get("MOONBRIDGE_MAX_OUTPUT_CHARS", "120000"))
MAX_RESPONSE_BYTES = int(os.environ.get("MOONBRIDGE_MAX_RESPONSE_BYTES", "5000000"))
if MAX_RESPONSE_BYTES < 1_000 or MAX_RESPONSE_BYTES > 50_000_000:
    raise ValueError("MOONBRIDGE_MAX_RESPONSE_BYTES must be between 1000 and 50000000")
_SANDBOX_ENV = os.environ.get("MOONBRIDGE_SANDBOX", "").strip().lower()
SANDBOX_MODE = _SANDBOX_ENV in {"1", "true", "yes", "copy"}
SANDBOX_KEEP = os.environ.get("MOONBRIDGE_SANDBOX_KEEP", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
SANDBOX_MAX_DIFF_BYTES = int(os.environ.get("MOONBRIDGE_SANDBOX_MAX_DIFF", "500000"))
SANDBOX_MAX_COPY_BYTES = int(
    os.environ.get("MOONBRIDGE_SANDBOX_MAX_COPY", str(500 * 1024 * 1024))
)

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


def _validate_allowed_dirs() -> None:
    if not ALLOWED_DIRS:
        return
    missing_count = 0
    for path in ALLOWED_DIRS:
        if os.path.isdir(path):
            continue
        missing_count += 1
        logger.warning("MOONBRIDGE_ALLOWED_DIRS entry does not exist: %s", path)
    if missing_count == len(ALLOWED_DIRS) and STRICT_MODE:
        message = "MOONBRIDGE_ALLOWED_DIRS entries do not exist"
        logger.error(message)
        print(message, file=sys.stderr)
        sys.exit(1)


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
    """Resolve model: param > adapter env > global env > adapter default > None.

    All values are validated and normalized.
    """
    if validated := _validate_model(model_param):
        return validated
    adapter_env = f"MOONBRIDGE_{adapter.config.name.upper()}_MODEL"
    if validated := _validate_model(os.environ.get(adapter_env)):
        return validated
    if validated := _validate_model(os.environ.get("MOONBRIDGE_MODEL")):
        return validated
    return adapter.config.default_model


def _resolve_reasoning_effort(
    adapter: CLIAdapter, reasoning_effort_param: str | None
) -> str | None:
    if reasoning_effort_param and (value := reasoning_effort_param.strip()):
        return value
    return adapter.config.default_reasoning_effort


def _preflight_check(adapter: CLIAdapter, agent_index: int = 0) -> AgentResult | None:
    """Return an error AgentResult if adapter CLI is not available, else None."""
    installed, _path = adapter.check_installed()
    if not installed:
        return AgentResult(
            status="error",
            output="",
            stderr=f"{adapter.config.name} CLI not found",
            returncode=-1,
            duration_ms=0,
            agent_index=agent_index,
            message=f"Install: {adapter.config.install_hint}",
        )
    return None


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


def _truncate_stream(
    value: str,
    max_chars: int,
    *,
    tail_only: bool = False,
) -> tuple[str, int | None]:
    if max_chars <= 0:
        if not value:
            return value, None
        return "... [truncated] ...", len(value)
    if len(value) <= max_chars:
        return value, None
    original_chars = len(value)
    if tail_only:
        return "... [truncated] ...\n" + value[-max_chars:], original_chars
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    omitted_chars = original_chars - max_chars
    truncated = (
        value[:head_chars]
        + f"\n... [truncated {omitted_chars} chars] ...\n"
        + value[-tail_chars:]
    )
    return truncated, original_chars


def _apply_output_limit(
    result: AgentResult,
    max_chars: int,
    *,
    tail_only: bool = False,
) -> AgentResult:
    stderr_original_chars: int | None = None
    if tail_only:
        output, output_original_chars = _truncate_stream(
            result.output,
            max_chars,
            tail_only=True,
        )
        stderr = result.stderr
        if stderr is not None:
            stderr, stderr_original_chars = _truncate_stream(
                stderr,
                max_chars,
                tail_only=True,
            )
    else:
        output_chars = len(result.output)
        stderr_chars = len(result.stderr or "")
        total_chars = output_chars + stderr_chars
        if total_chars <= max_chars:
            return result

        if stderr_chars == 0:
            output_budget = max_chars
            stderr_budget = 0
        elif output_chars == 0:
            output_budget = 0
            stderr_budget = max_chars
        else:
            output_budget = max(1, int(max_chars * (output_chars / total_chars)))
            stderr_budget = max_chars - output_budget
            if stderr_budget <= 0:
                stderr_budget = 1
                output_budget = max_chars - 1

        output, output_original_chars = _truncate_stream(result.output, output_budget)
        stderr = result.stderr
        if stderr is not None:
            stderr, stderr_original_chars = _truncate_stream(stderr, stderr_budget)

    if output_original_chars is None and stderr_original_chars is None:
        return result

    raw = dict(result.raw or {})
    limit_payload = dict(raw.get("output_limit") or {})
    limit_payload["max_chars"] = max_chars
    limit_payload["scope"] = "per_stream" if tail_only else "combined_streams"
    if output_original_chars is not None:
        limit_payload["stdout_original_chars"] = output_original_chars
    if stderr_original_chars is not None:
        limit_payload["stderr_original_chars"] = stderr_original_chars
    raw["output_limit"] = limit_payload
    return replace(result, output=output, stderr=stderr, raw=raw)


def _run_cli_sandboxed(
    adapter: CLIAdapter,
    prompt: str,
    thinking: bool,
    cwd: str,
    timeout_seconds: int,
    agent_index: int,
    model: str | None = None,
    reasoning_effort: str | None = None,
    request_id: str | None = None,
) -> AgentResult:
    from moonbridge.sandbox import run_sandboxed

    def run_agent(sandbox_cwd: str) -> AgentResult:
        return _run_cli_sync(
            adapter,
            prompt,
            thinking,
            sandbox_cwd,
            timeout_seconds,
            agent_index,
            model,
            reasoning_effort,
            request_id,
        )

    run_agent.agent_index = agent_index  # type: ignore[attr-defined]

    result, sandbox_result = run_sandboxed(
        run_agent,
        cwd,
        max_diff_bytes=SANDBOX_MAX_DIFF_BYTES,
        max_copy_bytes=SANDBOX_MAX_COPY_BYTES,
        keep=SANDBOX_KEEP,
    )
    if sandbox_result:
        raw = dict(result.raw or {})
        raw["sandbox"] = {
            "enabled": True,
            "summary": sandbox_result.summary,
            "diff": sandbox_result.diff,
            "truncated": sandbox_result.truncated,
        }
        if sandbox_result.sandbox_path:
            raw["sandbox"]["path"] = sandbox_result.sandbox_path
        return replace(result, raw=raw)
    return result


def _run_cli_sync(
    adapter: CLIAdapter,
    prompt: str,
    thinking: bool,
    cwd: str,
    timeout_seconds: int,
    agent_index: int,
    model: str | None = None,
    reasoning_effort: str | None = None,
    request_id: str | None = None,
) -> AgentResult:
    start = time.monotonic()
    with trace_span(
        f"agent/{agent_index}",
        attributes={
            "moonbridge.adapter": adapter.config.name,
            "moonbridge.agent_index": agent_index,
            "moonbridge.timeout_seconds": timeout_seconds,
            "moonbridge.prompt_length": len(prompt),
            "moonbridge.model": model or "",
            "moonbridge.request_id": request_id or "",
        },
    ) as span:

        def _finish(result: AgentResult) -> AgentResult:
            if span:
                try:
                    span.set_attribute("moonbridge.status", result.status)
                    span.set_attribute("moonbridge.duration_ms", result.duration_ms)
                except Exception as exc:
                    logger.debug("Failed to set span attributes: %s", exc)
            return result

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
            return _finish(
                AgentResult(
                    status="error",
                    output="",
                    stderr=f"{adapter.config.name} CLI not found or not executable",
                    returncode=-1,
                    duration_ms=duration_ms,
                    agent_index=agent_index,
                    request_id=request_id,
                )
            )
        except PermissionError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error("Permission denied starting process: %s", exc)
            return _finish(
                AgentResult(
                    status="error",
                    output="",
                    stderr=f"Permission denied: {exc}",
                    returncode=-1,
                    duration_ms=duration_ms,
                    agent_index=agent_index,
                    request_id=request_id,
                )
            )
        except OSError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error("Failed to start process: %s", exc)
            return _finish(
                AgentResult(
                    status="error",
                    output="",
                    stderr=f"Failed to start process: {exc}",
                    returncode=-1,
                    duration_ms=duration_ms,
                    agent_index=agent_index,
                    request_id=request_id,
                )
            )
        _track_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout_seconds)
            duration_ms = int((time.monotonic() - start) * 1000)
            stderr_value = stderr or None
            if _auth_error(stderr_value, adapter):
                logger.info(
                    "Agent %s completed with status: auth_error",
                    agent_index,
                    extra={"request_id": request_id, "adapter": adapter.config.name},
                )
                return _finish(
                    _apply_output_limit(
                        AgentResult(
                            status="auth_error",
                            output=stdout,
                            stderr=stderr_value,
                            returncode=proc.returncode,
                            duration_ms=duration_ms,
                            agent_index=agent_index,
                            message=adapter.config.auth_message,
                            request_id=request_id,
                        ),
                        MAX_OUTPUT_CHARS,
                    )
                )
            status = "success" if proc.returncode == 0 else "error"
            logger.info(
                "Agent %s completed with status: %s",
                agent_index,
                status,
                extra={"request_id": request_id, "adapter": adapter.config.name},
            )
            result = AgentResult(
                status=status,
                output=stdout,
                stderr=stderr_value,
                returncode=proc.returncode,
                duration_ms=duration_ms,
                agent_index=agent_index,
                request_id=request_id,
            )
            if result.status == "success":
                signals = extract_quality_signals(result.output, result.stderr)
                if signals:
                    raw = dict(result.raw or {})
                    raw["quality_signals"] = signals
                    result = replace(result, raw=raw)
            return _finish(_apply_output_limit(result, MAX_OUTPUT_CHARS))
        except TimeoutExpired:
            _terminate_process(proc)
            duration_ms = int((time.monotonic() - start) * 1000)
            partial_stdout = ""
            partial_stderr = ""
            try:
                remaining_out, remaining_err = proc.communicate(timeout=5)
                partial_stdout = remaining_out or ""
                partial_stderr = remaining_err or ""
            except Exception:
                try:
                    if proc.stdout:
                        partial_stdout = proc.stdout.read() or ""
                except Exception:
                    pass
                try:
                    if proc.stderr:
                        partial_stderr = proc.stderr.read() or ""
                except Exception:
                    pass
            if not isinstance(partial_stdout, str):
                partial_stdout = str(partial_stdout)
            if not isinstance(partial_stderr, str):
                partial_stderr = str(partial_stderr)
            captured_stdout_len = len(partial_stdout)
            captured_stderr_len = len(partial_stderr)
            logger.warning(
                "Agent %s timed out after %ss (captured %d chars stdout, %d chars stderr)",
                agent_index,
                timeout_seconds,
                captured_stdout_len,
                captured_stderr_len,
            )
            return _finish(
                _apply_output_limit(
                    AgentResult(
                        status="timeout",
                        output=partial_stdout,
                        stderr=partial_stderr or None,
                        returncode=-1,
                        duration_ms=duration_ms,
                        agent_index=agent_index,
                        message=f"Agent timed out after {timeout_seconds}s",
                        request_id=request_id,
                    ),
                    _TIMEOUT_TAIL_CHARS,
                    tail_only=True,
                )
            )
        except Exception as exc:
            _terminate_process(proc)
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error("Agent %s failed with error: %s", agent_index, exc)
            return _finish(
                AgentResult(
                    status="error",
                    output="",
                    stderr=str(exc),
                    returncode=-1,
                    duration_ms=duration_ms,
                    agent_index=agent_index,
                    request_id=request_id,
                )
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
    request_id: str | None = None,
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
            request_id,
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
        request_id,
    )


def _json_text(payload: Any) -> list[TextContent]:
    """Serialize payload for MCP text transport."""
    return tool_handlers.json_text(payload)


def _enforce_response_limit(content: list[TextContent], tool_name: str) -> list[TextContent]:
    """Apply circuit-breaker behavior for oversized protocol responses."""
    return tool_handlers.enforce_response_limit(
        content,
        tool_name,
        max_response_bytes=MAX_RESPONSE_BYTES,
        logger=logger,
    )


def _status_check(cwd: str, adapter: CLIAdapter) -> dict[str, Any]:
    config = {
        "strict_mode": STRICT_MODE,
        "allowed_dirs": ALLOWED_DIRS or None,
        "unrestricted": not ALLOWED_DIRS,
        "cwd": cwd,
    }
    installed, _path = adapter.check_installed()
    if not installed:
        return {
            "status": "error",
            "message": (
                f"{adapter.config.name} CLI not found. Install: {adapter.config.install_hint}"
            ),
            "config": config,
        }
    timeout = min(DEFAULT_TIMEOUT, 60)
    result = _run_cli_sync(adapter, "status check", False, cwd, timeout, 0)
    if result.status == "auth_error":
        return {
            "status": "auth_error",
            "message": adapter.config.auth_message,
            "config": config,
        }
    if result.status == "success":
        return {
            "status": "success",
            "message": f"{adapter.config.name} CLI available and authenticated",
            "config": config,
        }
    return {
        "status": "error",
        "message": f"{adapter.config.name} CLI error",
        "details": result.to_dict(),
        "config": config,
    }


def _model_catalog(
    cwd: str,
    adapter: CLIAdapter,
    provider: str | None,
    refresh: bool,
) -> dict[str, Any]:
    if provider and adapter.config.name != "opencode":
        return {
            "status": "error",
            "message": (
                "provider filter is only supported for opencode "
                f"(got {adapter.config.name})"
            ),
        }

    installed, _path = adapter.check_installed()
    if not installed:
        return {
            "status": "error",
            "message": (
                f"{adapter.config.name} CLI not found. Install: {adapter.config.install_hint}"
            ),
            "adapter": adapter.config.name,
            "provider": provider,
            "refresh": refresh,
            "models": [],
        }

    timeout = min(DEFAULT_TIMEOUT, 120)
    try:
        models, source = adapter.list_models(
            cwd,
            provider=provider,
            refresh=refresh,
            timeout_seconds=timeout,
        )
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "adapter": adapter.config.name,
            "provider": provider,
            "refresh": refresh,
            "models": [],
        }

    deduped_models: list[str] = []
    seen: set[str] = set()
    for model in models:
        normalized = model.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped_models.append(normalized)

    return {
        "status": "success",
        "adapter": adapter.config.name,
        "provider": provider,
        "refresh": refresh,
        "source": source,
        "count": len(deduped_models),
        "models": deduped_models,
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
    """Build MCP tool metadata for all registered adapters."""
    adapter_names = tuple(ADAPTER_REGISTRY.keys())
    adapters = ", ".join(adapter_names)
    tool_desc = (
        "Spawn an AI coding agent using adapter CLIs. "
        f"Available adapters: {adapters}."
    )
    status_desc = (
        "Verify an adapter CLI is installed and authenticated. "
        "Defaults to MOONBRIDGE_ADAPTER when adapter is omitted."
    )
    return build_tools(
        adapter_names=adapter_names,
        default_timeout=DEFAULT_TIMEOUT,
        tool_description=tool_desc,
        status_description=status_desc,
    )


def _build_tool_handler_deps() -> tool_handlers.ToolHandlerDeps:
    """Collect orchestration callbacks for protocol-layer dispatch."""
    return tool_handlers.ToolHandlerDeps(
        max_parallel_agents=MAX_PARALLEL_AGENTS,
        adapter_registry=ADAPTER_REGISTRY,
        validate_cwd=_validate_cwd,
        get_adapter=get_adapter,
        validate_prompt=_validate_prompt,
        validate_thinking=_validate_thinking,
        resolve_timeout=_resolve_timeout,
        resolve_model=_resolve_model,
        resolve_reasoning_effort=_resolve_reasoning_effort,
        preflight_check=_preflight_check,
        run_cli=_run_cli,
        adapter_info=_adapter_info,
        model_catalog=_model_catalog,
        status_check=_status_check,
    )


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a tool invocation with validation and stable error payloads.

    Separated from ``call_tool`` so tests can invoke tool logic without the
    MCP decorator.

    Args:
        name: MCP tool name (``spawn_agent``, ``spawn_agents_parallel``, etc.).
        arguments: Tool argument payload from the MCP client.
    """
    return await tool_handlers.handle_tool(
        name,
        arguments,
        deps=_build_tool_handler_deps(),
        logger=logger,
    )


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """MCP tool handler -- delegates to ``handle_tool`` with response limit."""
    return _enforce_response_limit(await handle_tool(name, arguments), name)


async def run() -> None:
    """Run the MCP server over stdio until the client disconnects."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """CLI entry point that validates prerequisites then starts the server."""
    _configure_logging()
    _warn_if_unrestricted()
    _validate_allowed_dirs()
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
