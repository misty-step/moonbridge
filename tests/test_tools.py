"""Tests for the tools module."""

import pytest

from moonbridge.tools import (
    ParameterDef,
    ToolDef,
    _param_to_schema,
    build_input_schema,
    build_tools,
)


class TestParameterDefToSchema:
    """Tests for _param_to_schema conversion."""

    def test_string_param_with_description(self):
        """String parameter with description converts correctly."""
        param = ParameterDef(
            type="string",
            description="A test string parameter",
        )
        schema = _param_to_schema(param)

        assert schema == {
            "type": "string",
            "description": "A test string parameter",
        }

    def test_integer_param_with_min_max(self):
        """Integer parameter with min/max constraints converts correctly."""
        param = ParameterDef(
            type="integer",
            description="A bounded integer",
            minimum=10,
            maximum=100,
        )
        schema = _param_to_schema(param)

        assert schema == {
            "type": "integer",
            "description": "A bounded integer",
            "minimum": 10,
            "maximum": 100,
        }

    def test_boolean_param_with_default(self):
        """Boolean parameter with default value converts correctly."""
        param = ParameterDef(
            type="boolean",
            description="A boolean flag",
            default=True,
        )
        schema = _param_to_schema(param)

        assert schema == {
            "type": "boolean",
            "description": "A boolean flag",
            "default": True,
        }

    def test_enum_param(self):
        """Enum parameter converts tuple to list."""
        param = ParameterDef(
            type="string",
            description="Choose a level",
            enum=("low", "medium", "high"),
        )
        schema = _param_to_schema(param)

        assert schema == {
            "type": "string",
            "description": "Choose a level",
            "enum": ["low", "medium", "high"],
        }


class TestBuildInputSchema:
    """Tests for build_input_schema function."""

    def test_adapter_enum_populated(self):
        """Adapter parameter gets dynamic enum from adapter_names."""
        tool = ToolDef(
            name="test_tool",
            description_template="Test",
            parameters=(
                (
                    "adapter",
                    ParameterDef(
                        type="string",
                        description="Adapter to use",
                    ),
                ),
            ),
        )
        schema = build_input_schema(tool, ("kimi", "codex", "claude"), 300)

        assert schema["properties"]["adapter"]["enum"] == ["kimi", "codex", "claude"]

    def test_timeout_default_populated(self):
        """Timeout parameter gets dynamic default from default_timeout."""
        tool = ToolDef(
            name="test_tool",
            description_template="Test",
            parameters=(
                (
                    "timeout_seconds",
                    ParameterDef(
                        type="integer",
                        description="Timeout",
                        minimum=30,
                        maximum=3600,
                    ),
                ),
            ),
        )
        schema = build_input_schema(tool, ("kimi",), 450)

        assert schema["properties"]["timeout_seconds"]["default"] == 450


class TestBuildTools:
    """Tests for build_tools function."""

    @pytest.fixture
    def tools(self):
        """Build tools with test values."""
        return build_tools(
            adapter_names=("kimi", "codex"),
            default_timeout=600,
            tool_description="Spawn a Kimi agent",
            status_description="Check Kimi CLI status",
        )

    def test_returns_exactly_four_tools(self, tools):
        """build_tools returns exactly 4 tools."""
        assert len(tools) == 4

    def test_tool_names_correct(self, tools):
        """All tool names are present and correct."""
        names = [t.name for t in tools]
        assert names == [
            "spawn_agent",
            "spawn_agents_parallel",
            "list_adapters",
            "check_status",
        ]

    def test_spawn_agent_required_prompt(self, tools):
        """spawn_agent requires 'prompt' parameter."""
        spawn_agent = tools[0]
        assert spawn_agent.name == "spawn_agent"
        assert spawn_agent.inputSchema["required"] == ["prompt"]

    def test_spawn_agents_parallel_required_agents(self, tools):
        """spawn_agents_parallel requires 'agents' parameter."""
        parallel = tools[1]
        assert parallel.name == "spawn_agents_parallel"
        assert parallel.inputSchema["required"] == ["agents"]

    def test_list_adapters_empty_required(self, tools):
        """list_adapters has no required parameters."""
        list_adapters = tools[2]
        assert list_adapters.name == "list_adapters"
        assert "required" not in list_adapters.inputSchema

    def test_check_status_empty_required(self, tools):
        """check_status has no required parameters."""
        check_status = tools[3]
        assert check_status.name == "check_status"
        assert "required" not in check_status.inputSchema


class TestSchemaEquivalence:
    """Tests verifying schema structure matches expected format."""

    @pytest.fixture
    def spawn_agent_tool(self):
        """Get spawn_agent tool for schema inspection."""
        tools = build_tools(
            adapter_names=("kimi", "codex"),
            default_timeout=600,
            tool_description="Test description",
            status_description="Status description",
        )
        return tools[0]

    def test_spawn_agent_has_all_expected_properties(self, spawn_agent_tool):
        """spawn_agent schema contains all expected properties."""
        props = spawn_agent_tool.inputSchema["properties"]

        expected_keys = {
            "prompt",
            "adapter",
            "thinking",
            "timeout_seconds",
            "model",
            "reasoning_effort",
        }
        assert set(props.keys()) == expected_keys

    def test_spawn_agent_prompt_schema(self, spawn_agent_tool):
        """prompt property has correct schema structure."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["prompt"]["type"] == "string"
        assert "description" in props["prompt"]

    def test_spawn_agent_adapter_schema(self, spawn_agent_tool):
        """adapter property has correct schema with enum."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["adapter"]["type"] == "string"
        assert props["adapter"]["enum"] == ["kimi", "codex"]

    def test_spawn_agent_thinking_schema(self, spawn_agent_tool):
        """thinking property has correct schema with default."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["thinking"]["type"] == "boolean"
        assert props["thinking"]["default"] is False

    def test_spawn_agent_timeout_schema(self, spawn_agent_tool):
        """timeout_seconds property has correct schema with bounds."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["timeout_seconds"]["type"] == "integer"
        assert props["timeout_seconds"]["minimum"] == 30
        assert props["timeout_seconds"]["maximum"] == 3600
        assert props["timeout_seconds"]["default"] == 600

    def test_spawn_agent_model_schema(self, spawn_agent_tool):
        """model property has correct schema."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["model"]["type"] == "string"
        assert "description" in props["model"]

    def test_spawn_agent_reasoning_effort_schema(self, spawn_agent_tool):
        """reasoning_effort property has correct schema with enum."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["reasoning_effort"]["type"] == "string"
        assert props["reasoning_effort"]["enum"] == ["low", "medium", "high", "xhigh"]
