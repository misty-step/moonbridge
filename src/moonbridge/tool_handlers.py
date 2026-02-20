"""MCP protocol-layer tool dispatch for moonbridge.server."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from mcp.types import TextContent

from moonbridge.adapters.base import AgentResult, CLIAdapter
from moonbridge.telemetry import generate_request_id, trace_span

RunCliFn = Callable[
    [CLIAdapter, str, bool, str, int, int, str | None, str | None, str | None],
    AgentResult,
]


@dataclass(frozen=True)
class ToolHandlerDeps:
    """Protocol-facing dependencies from the orchestration layer."""

    max_parallel_agents: int
    adapter_registry: Mapping[str, CLIAdapter]
    validate_cwd: Callable[[str | None], str]
    get_adapter: Callable[[str | None], CLIAdapter]
    validate_prompt: Callable[[str], str]
    validate_thinking: Callable[[CLIAdapter, bool], bool]
    resolve_timeout: Callable[[CLIAdapter, int | None], int]
    resolve_model: Callable[[CLIAdapter, str | None], str | None]
    resolve_reasoning_effort: Callable[[CLIAdapter, str | None], str | None]
    preflight_check: Callable[[CLIAdapter, int], AgentResult | None]
    run_cli: RunCliFn
    adapter_info: Callable[[str, CLIAdapter], dict[str, Any]]
    model_catalog: Callable[[str, CLIAdapter, str | None, bool], dict[str, Any]]
    status_check: Callable[[str, CLIAdapter], dict[str, Any]]


def json_text(payload: Any) -> list[TextContent]:
    """Serialize payload into the MCP text transport format."""
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=True))]


def enforce_response_limit(
    content: list[TextContent],
    tool_name: str,
    *,
    max_response_bytes: int,
    logger: logging.Logger,
) -> list[TextContent]:
    """Replace oversized MCP responses with a compact error payload."""
    serialized = json.dumps(
        [{"type": item.type, "text": item.text} for item in content],
        ensure_ascii=True,
    )
    total_bytes = len(serialized)
    if total_bytes <= max_response_bytes:
        return content

    logger.warning(
        "Response payload exceeded limit for %s: %d bytes (max %d)",
        tool_name,
        total_bytes,
        max_response_bytes,
    )
    return json_text(
        {
            "status": "error",
            "message": "Response payload too large",
            "circuit_breaker": {
                "triggered": True,
                "original_bytes": total_bytes,
                "max_bytes": max_response_bytes,
                "tool": tool_name[:200],
            },
        }
    )


async def handle_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    deps: ToolHandlerDeps,
    logger: logging.Logger,
) -> list[TextContent]:
    """Dispatch MCP tool calls while delegating execution to orchestration deps."""
    request_id = generate_request_id()
    try:
        with trace_span(
            f"handle_tool/{name}",
            attributes={
                "moonbridge.tool": name,
                "moonbridge.request_id": request_id,
            },
        ):
            cwd = deps.validate_cwd(None)

            if name == "spawn_agent":
                adapter = deps.get_adapter(arguments.get("adapter"))
                prompt = deps.validate_prompt(arguments["prompt"])
                thinking = deps.validate_thinking(adapter, bool(arguments.get("thinking", False)))
                timeout_seconds = deps.resolve_timeout(adapter, arguments.get("timeout_seconds"))
                model = deps.resolve_model(adapter, arguments.get("model"))
                reasoning_effort = deps.resolve_reasoning_effort(
                    adapter, arguments.get("reasoning_effort")
                )
                preflight = deps.preflight_check(adapter, 0)
                if preflight:
                    return json_text(replace(preflight, request_id=request_id).to_dict())

                loop = asyncio.get_running_loop()
                try:
                    result = await loop.run_in_executor(
                        None,
                        deps.run_cli,
                        adapter,
                        prompt,
                        thinking,
                        cwd,
                        timeout_seconds,
                        0,
                        model,
                        reasoning_effort,
                        request_id,
                    )
                except asyncio.CancelledError:
                    return json_text(
                        AgentResult(
                            status="cancelled",
                            output="",
                            stderr=None,
                            returncode=-1,
                            duration_ms=0,
                            agent_index=0,
                            request_id=request_id,
                        ).to_dict()
                    )
                return json_text(result.to_dict())

            if name == "spawn_agents_parallel":
                agents = list(arguments["agents"])
                if len(agents) > deps.max_parallel_agents:
                    raise ValueError(f"Max {deps.max_parallel_agents} agents allowed")

                loop = asyncio.get_running_loop()
                tasks = []
                results: list[AgentResult] = []
                for idx, spec in enumerate(agents):
                    adapter = deps.get_adapter(spec.get("adapter"))
                    prompt = deps.validate_prompt(spec["prompt"])
                    thinking = deps.validate_thinking(adapter, bool(spec.get("thinking", False)))
                    model = deps.resolve_model(adapter, spec.get("model"))
                    reasoning_effort = deps.resolve_reasoning_effort(
                        adapter, spec.get("reasoning_effort")
                    )
                    preflight = deps.preflight_check(adapter, idx)
                    if preflight:
                        results.append(replace(preflight, request_id=request_id))
                        continue
                    tasks.append(
                        loop.run_in_executor(
                            None,
                            deps.run_cli,
                            adapter,
                            prompt,
                            thinking,
                            cwd,
                            deps.resolve_timeout(adapter, spec.get("timeout_seconds")),
                            idx,
                            model,
                            reasoning_effort,
                            request_id,
                        )
                    )

                try:
                    task_results = await asyncio.gather(*tasks) if tasks else []
                except asyncio.CancelledError:
                    cancelled = [
                        AgentResult(
                            status="cancelled",
                            output="",
                            stderr=None,
                            returncode=-1,
                            duration_ms=0,
                            agent_index=idx,
                            request_id=request_id,
                        )
                        for idx in range(len(agents))
                    ]
                    return json_text([item.to_dict() for item in cancelled])

                results.extend(task_results)
                results.sort(key=lambda item: item.agent_index)
                return json_text([item.to_dict() for item in results])

            if name == "list_adapters":
                info = [
                    deps.adapter_info(cwd, adapter) for adapter in deps.adapter_registry.values()
                ]
                return json_text(info)

            if name == "list_models":
                adapter = deps.get_adapter(arguments.get("adapter"))
                provider_raw = arguments.get("provider")
                provider = provider_raw.strip() if isinstance(provider_raw, str) else None
                provider = provider or None
                refresh = bool(arguments.get("refresh", False))
                return json_text(deps.model_catalog(cwd, adapter, provider, refresh))

            if name == "check_status":
                adapter = deps.get_adapter(arguments.get("adapter"))
                return json_text(deps.status_check(cwd, adapter))

            return json_text({"status": "error", "message": f"Unknown tool: {name}"})
    except ValueError as exc:
        logger.warning("Validation error: %s", exc)
        return json_text({"status": "error", "message": str(exc)})
    except Exception as exc:
        logger.error("Unhandled error: %s", exc)
        return json_text({"status": "error", "message": str(exc)})
