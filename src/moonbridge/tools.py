"""Tool schema definitions for Moonbridge MCP server.

This module provides dataclasses and functions for defining MCP tool schemas
in a reusable, type-safe manner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.types import Tool


@dataclass(frozen=True)
class ParameterDef:
    """Definition for a JSON Schema parameter."""

    type: str  # "string", "integer", "boolean", "array"
    description: str
    default: Any = None
    enum: tuple[str, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None
    items: dict[str, Any] | None = None  # For array types


@dataclass(frozen=True)
class ToolDef:
    """Definition for an MCP tool."""

    name: str
    description_template: str  # May contain {adapter} placeholder
    parameters: tuple[tuple[str, ParameterDef], ...]  # Ordered (name, param) pairs
    required: tuple[str, ...] = ()


# =============================================================================
# Reusable parameter definitions
# =============================================================================

PROMPT_PARAM = ParameterDef(
    type="string",
    description="Instructions for the agent (task, context, constraints)",
)

# Note: ADAPTER_PARAM enum is populated dynamically via build_adapter_param()
ADAPTER_PARAM_BASE = ParameterDef(
    type="string",
    description=(
        "Backend to use. Defaults to MOONBRIDGE_ADAPTER env var "
        "(falls back to kimi when unset)."
    ),
    # enum is set dynamically
)

THINKING_PARAM = ParameterDef(
    type="boolean",
    description="Enable extended reasoning mode for complex tasks",
    default=False,
)

# Note: TIMEOUT_PARAM default is populated dynamically
TIMEOUT_PARAM_BASE = ParameterDef(
    type="integer",
    description=(
        "Max execution time (30-3600s). Adapter-specific defaults apply when unset. "
        "Complex implementations may need full 30min+."
    ),
    minimum=30,
    maximum=3600,
    # default is set dynamically
)

MODEL_PARAM = ParameterDef(
    type="string",
    description=(
        "Model to use (e.g., 'gpt-5.2-codex', 'kimi-k2.5', "
        "'openrouter/minimax/minimax-m2.5', 'gemini-2.5-pro'). "
        "Falls back to MOONBRIDGE_{ADAPTER}_MODEL or MOONBRIDGE_MODEL env vars."
    ),
)

# Shorter model description for nested items
MODEL_PARAM_SHORT = ParameterDef(
    type="string",
    description=(
        "Model to use. Falls back to "
        "MOONBRIDGE_{ADAPTER}_MODEL or MOONBRIDGE_MODEL env vars."
    ),
)

REASONING_EFFORT_PARAM = ParameterDef(
    type="string",
    description=(
        "Reasoning effort for Codex (low, medium, high, xhigh). "
        "Ignored for non-Codex adapters."
    ),
    enum=("low", "medium", "high", "xhigh"),
)

# Alias: reasoning_effort description is already concise enough for nested items.
REASONING_EFFORT_PARAM_SHORT = REASONING_EFFORT_PARAM

PROVIDER_PARAM = ParameterDef(
    type="string",
    description=(
        "Optional provider filter for model listing (OpenCode only). "
        "Example: 'openrouter'."
    ),
)

REFRESH_PARAM = ParameterDef(
    type="boolean",
    description="Refresh model catalog from provider/CLI where supported.",
    default=False,
)


# =============================================================================
# Helper functions for dynamic parameter creation
# =============================================================================


def _build_adapter_param(adapter_names: tuple[str, ...]) -> ParameterDef:
    """Create adapter parameter with dynamic enum."""
    return ParameterDef(
        type="string",
        description=ADAPTER_PARAM_BASE.description,
        enum=adapter_names,
    )


def _build_timeout_param(default_timeout: int) -> ParameterDef:
    """Create timeout parameter with dynamic default.

    Raises:
        ValueError: If default_timeout is outside the valid range.
    """
    min_timeout = TIMEOUT_PARAM_BASE.minimum
    max_timeout = TIMEOUT_PARAM_BASE.maximum
    if min_timeout is not None and default_timeout < min_timeout:
        raise ValueError(f"default_timeout must be >= {min_timeout}, got {default_timeout}")
    if max_timeout is not None and default_timeout > max_timeout:
        raise ValueError(f"default_timeout must be <= {max_timeout}, got {default_timeout}")
    return ParameterDef(
        type="integer",
        description=TIMEOUT_PARAM_BASE.description,
        default=default_timeout,
        minimum=min_timeout,
        maximum=max_timeout,
    )


# =============================================================================
# Tool definitions
# =============================================================================

SPAWN_AGENT_TOOL = ToolDef(
    name="spawn_agent",
    description_template="{tool_description}",
    parameters=(
        ("prompt", PROMPT_PARAM),
        ("adapter", ADAPTER_PARAM_BASE),  # Will be replaced with dynamic version
        ("thinking", THINKING_PARAM),
        ("timeout_seconds", TIMEOUT_PARAM_BASE),  # Will be replaced with dynamic version
        ("model", MODEL_PARAM),
        ("reasoning_effort", REASONING_EFFORT_PARAM),
    ),
    required=("prompt",),
)

SPAWN_AGENTS_PARALLEL_TOOL = ToolDef(
    name="spawn_agents_parallel",
    description_template="{tool_description} Run multiple agents in parallel.",
    parameters=(),  # Handled specially due to array items
    required=("agents",),
)

LIST_ADAPTERS_TOOL = ToolDef(
    name="list_adapters",
    description_template="List available adapters and their status",
    parameters=(),
    required=(),
)

CHECK_STATUS_TOOL = ToolDef(
    name="check_status",
    description_template="{status_description}",
    parameters=(("adapter", ADAPTER_PARAM_BASE),),
    required=(),
)

LIST_MODELS_TOOL = ToolDef(
    name="list_models",
    description_template="List model options for an adapter (static and/or dynamic catalogs).",
    parameters=(
        ("adapter", ADAPTER_PARAM_BASE),
        ("provider", PROVIDER_PARAM),
        ("refresh", REFRESH_PARAM),
    ),
    required=(),
)


# =============================================================================
# Schema generation functions
# =============================================================================


def _param_to_schema(param: ParameterDef) -> dict[str, Any]:
    """Convert a ParameterDef to a JSON Schema dict."""
    schema: dict[str, Any] = {"type": param.type}

    if param.description:
        schema["description"] = param.description
    if param.default is not None:
        schema["default"] = param.default
    if param.enum is not None:
        schema["enum"] = list(param.enum)
    if param.minimum is not None:
        schema["minimum"] = param.minimum
    if param.maximum is not None:
        schema["maximum"] = param.maximum
    if param.items is not None:
        schema["items"] = param.items

    return schema


def build_input_schema(
    tool: ToolDef,
    adapter_names: tuple[str, ...],
    default_timeout: int,
) -> dict[str, Any]:
    """Convert ToolDef to MCP inputSchema dict.

    Args:
        tool: The tool definition to convert.
        adapter_names: Tuple of available adapter names for enum.
        default_timeout: Default timeout value for timeout parameters.

    Returns:
        A JSON Schema dict suitable for MCP Tool.inputSchema.
    """
    properties: dict[str, Any] = {}

    for name, param in tool.parameters:
        # Handle dynamic parameters
        if name == "adapter":
            param = _build_adapter_param(adapter_names)
        elif name == "timeout_seconds":
            param = _build_timeout_param(default_timeout)

        properties[name] = _param_to_schema(param)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }

    if tool.required:
        schema["required"] = list(tool.required)

    return schema


def _build_agents_array_schema(
    adapter_names: tuple[str, ...],
    default_timeout: int,
) -> dict[str, Any]:
    """Build the schema for the agents array in spawn_agents_parallel."""
    adapter_schema = _param_to_schema(_build_adapter_param(adapter_names))
    timeout_schema = _param_to_schema(_build_timeout_param(default_timeout))

    return {
        "type": "array",
        "description": "List of agent specs with prompt and optional settings",
        "items": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "adapter": adapter_schema,
                "thinking": {"type": "boolean", "default": False},
                "timeout_seconds": timeout_schema,
                "model": _param_to_schema(MODEL_PARAM_SHORT),
                "reasoning_effort": _param_to_schema(REASONING_EFFORT_PARAM_SHORT),
            },
            "required": ["prompt"],
        },
    }


def build_tools(
    adapter_names: tuple[str, ...],
    default_timeout: int,
    tool_description: str,
    status_description: str,
) -> list[Tool]:
    """Build all MCP Tool objects from definitions.

    Args:
        adapter_names: Tuple of available adapter names.
        default_timeout: Default timeout value in seconds.
        tool_description: Description for the spawn_agent tool.
        status_description: Description for the check_status tool.

    Returns:
        List of MCP Tool objects ready for registration.
    """
    # spawn_agent
    spawn_agent_schema = build_input_schema(
        SPAWN_AGENT_TOOL, adapter_names, default_timeout
    )

    # spawn_agents_parallel (special handling for array)
    parallel_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agents": _build_agents_array_schema(adapter_names, default_timeout),
        },
        "required": ["agents"],
    }

    # list_adapters
    list_adapters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    # check_status
    check_status_schema = build_input_schema(
        CHECK_STATUS_TOOL,
        adapter_names,
        default_timeout,
    )

    # list_models
    list_models_schema = build_input_schema(
        LIST_MODELS_TOOL,
        adapter_names,
        default_timeout,
    )

    return [
        Tool(
            name="spawn_agent",
            description=tool_description,
            inputSchema=spawn_agent_schema,
        ),
        Tool(
            name="spawn_agents_parallel",
            description=f"{tool_description} Run multiple agents in parallel.",
            inputSchema=parallel_schema,
        ),
        Tool(
            name="list_adapters",
            description="List available adapters and their status",
            inputSchema=list_adapters_schema,
        ),
        Tool(
            name="list_models",
            description="List model options for an adapter",
            inputSchema=list_models_schema,
        ),
        Tool(
            name="check_status",
            description=status_description,
            inputSchema=check_status_schema,
        ),
    ]


__all__ = ["build_tools"]
