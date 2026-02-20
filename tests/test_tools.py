"""Tests for the tools module.

Tests the public API (build_tools) by verifying output schemas.
Internal dataclasses and helpers are not tested directly - they're
implementation details verified through integration tests.
"""

import pytest

from moonbridge.tools import build_tools


class TestBuildTools:
    """Tests for build_tools function."""

    @pytest.fixture
    def tools(self):
        """Build tools with test values."""
        return build_tools(
            adapter_names=("kimi", "codex", "opencode", "gemini"),
            default_timeout=600,
            tool_description="Spawn a Kimi agent",
            status_description="Check Kimi CLI status",
        )

    def test_returns_exactly_five_tools(self, tools):
        """build_tools returns exactly 5 tools."""
        assert len(tools) == 5

    def test_tool_names_correct(self, tools):
        """All tool names are present and correct."""
        names = [t.name for t in tools]
        assert names == [
            "spawn_agent",
            "spawn_agents_parallel",
            "list_adapters",
            "list_models",
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
        check_status = tools[4]
        assert check_status.name == "check_status"
        assert "required" not in check_status.inputSchema

    def test_list_models_empty_required(self, tools):
        """list_models has no required parameters."""
        list_models = tools[3]
        assert list_models.name == "list_models"
        assert "required" not in list_models.inputSchema

    def test_check_status_schema_has_adapter_param(self, tools):
        """check_status supports optional adapter override."""
        check_status = tools[4]
        props = check_status.inputSchema["properties"]
        assert "adapter" in props


class TestSpawnAgentSchema:
    """Tests verifying spawn_agent schema structure."""

    @pytest.fixture
    def spawn_agent_tool(self):
        """Get spawn_agent tool for schema inspection."""
        tools = build_tools(
            adapter_names=("kimi", "codex", "opencode", "gemini"),
            default_timeout=600,
            tool_description="Test description",
            status_description="Status description",
        )
        return tools[0]

    def test_has_all_expected_properties(self, spawn_agent_tool):
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

    def test_prompt_schema(self, spawn_agent_tool):
        """prompt property has correct schema structure."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["prompt"]["type"] == "string"
        assert "description" in props["prompt"]

    def test_adapter_schema(self, spawn_agent_tool):
        """adapter property has correct schema with enum."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["adapter"]["type"] == "string"
        assert props["adapter"]["enum"] == ["kimi", "codex", "opencode", "gemini"]

    def test_thinking_schema(self, spawn_agent_tool):
        """thinking property has correct schema with default."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["thinking"]["type"] == "boolean"
        assert props["thinking"]["default"] is False

    def test_timeout_schema(self, spawn_agent_tool):
        """timeout_seconds property has correct schema with bounds."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["timeout_seconds"]["type"] == "integer"
        assert props["timeout_seconds"]["minimum"] == 30
        assert props["timeout_seconds"]["maximum"] == 3600
        assert props["timeout_seconds"]["default"] == 600

    def test_model_schema(self, spawn_agent_tool):
        """model property has correct schema."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["model"]["type"] == "string"
        assert "description" in props["model"]

    def test_reasoning_effort_schema(self, spawn_agent_tool):
        """reasoning_effort property has correct schema with enum."""
        props = spawn_agent_tool.inputSchema["properties"]

        assert props["reasoning_effort"]["type"] == "string"
        assert props["reasoning_effort"]["enum"] == ["low", "medium", "high", "xhigh"]


class TestSpawnAgentsParallelSchema:
    """Tests verifying spawn_agents_parallel schema structure."""

    @pytest.fixture
    def parallel_tool(self):
        """Get spawn_agents_parallel tool for schema inspection."""
        tools = build_tools(
            adapter_names=("kimi", "codex", "opencode", "gemini"),
            default_timeout=600,
            tool_description="Test description",
            status_description="Status description",
        )
        return tools[1]

    def test_agents_is_array(self, parallel_tool):
        """agents property is an array type."""
        props = parallel_tool.inputSchema["properties"]
        assert props["agents"]["type"] == "array"

    def test_agents_items_has_required_prompt(self, parallel_tool):
        """agents items require prompt."""
        props = parallel_tool.inputSchema["properties"]
        items = props["agents"]["items"]
        assert items["required"] == ["prompt"]

    def test_agents_items_has_all_properties(self, parallel_tool):
        """agents items have all expected properties."""
        props = parallel_tool.inputSchema["properties"]
        item_props = props["agents"]["items"]["properties"]

        expected_keys = {
            "prompt",
            "adapter",
            "thinking",
            "timeout_seconds",
            "model",
            "reasoning_effort",
        }
        assert set(item_props.keys()) == expected_keys


class TestDynamicParameterInjection:
    """Tests verifying dynamic parameters are correctly injected."""

    def test_adapter_enum_from_adapter_names(self):
        """Adapter enum comes from adapter_names argument."""
        tools = build_tools(
            adapter_names=("alpha", "beta", "gamma"),
            default_timeout=600,
            tool_description="Test",
            status_description="Status",
        )
        spawn_agent = tools[0]
        props = spawn_agent.inputSchema["properties"]

        assert props["adapter"]["enum"] == ["alpha", "beta", "gamma"]

    def test_timeout_default_from_default_timeout(self):
        """Timeout default comes from default_timeout argument."""
        tools = build_tools(
            adapter_names=("kimi",),
            default_timeout=999,
            tool_description="Test",
            status_description="Status",
        )
        spawn_agent = tools[0]
        props = spawn_agent.inputSchema["properties"]

        assert props["timeout_seconds"]["default"] == 999

    def test_tool_description_used(self):
        """tool_description is used in spawn_agent description."""
        tools = build_tools(
            adapter_names=("kimi",),
            default_timeout=600,
            tool_description="Custom spawn description",
            status_description="Status",
        )
        spawn_agent = tools[0]
        assert spawn_agent.description == "Custom spawn description"

    def test_status_description_used(self):
        """status_description is used in check_status description."""
        tools = build_tools(
            adapter_names=("kimi",),
            default_timeout=600,
            tool_description="Test",
            status_description="Custom status description",
        )
        check_status = tools[4]
        assert check_status.description == "Custom status description"


class TestListModelsSchema:
    """Tests verifying list_models schema structure."""

    @pytest.fixture
    def list_models_tool(self):
        tools = build_tools(
            adapter_names=("kimi", "codex", "opencode", "gemini"),
            default_timeout=600,
            tool_description="Test description",
            status_description="Status description",
        )
        return tools[3]

    def test_has_expected_properties(self, list_models_tool):
        props = list_models_tool.inputSchema["properties"]
        assert set(props.keys()) == {"adapter", "provider", "refresh"}

    def test_adapter_enum_uses_dynamic_adapter_names(self, list_models_tool):
        props = list_models_tool.inputSchema["properties"]
        assert props["adapter"]["enum"] == ["kimi", "codex", "opencode", "gemini"]

    def test_refresh_default_false(self, list_models_tool):
        props = list_models_tool.inputSchema["properties"]
        assert props["refresh"]["type"] == "boolean"
        assert props["refresh"]["default"] is False


class TestTimeoutValidation:
    """Tests for timeout bounds validation."""

    def test_timeout_below_minimum_raises(self):
        """default_timeout below minimum raises ValueError."""
        with pytest.raises(ValueError, match="must be >= 30"):
            build_tools(
                adapter_names=("kimi",),
                default_timeout=10,  # Below minimum of 30
                tool_description="Test",
                status_description="Status",
            )

    def test_timeout_above_maximum_raises(self):
        """default_timeout above maximum raises ValueError."""
        with pytest.raises(ValueError, match="must be <= 3600"):
            build_tools(
                adapter_names=("kimi",),
                default_timeout=5000,  # Above maximum of 3600
                tool_description="Test",
                status_description="Status",
            )

    def test_timeout_at_minimum_accepted(self):
        """default_timeout at minimum boundary is accepted."""
        tools = build_tools(
            adapter_names=("kimi",),
            default_timeout=30,  # Exactly at minimum
            tool_description="Test",
            status_description="Status",
        )
        props = tools[0].inputSchema["properties"]
        assert props["timeout_seconds"]["default"] == 30

    def test_timeout_at_maximum_accepted(self):
        """default_timeout at maximum boundary is accepted."""
        tools = build_tools(
            adapter_names=("kimi",),
            default_timeout=3600,  # Exactly at maximum
            tool_description="Test",
            status_description="Status",
        )
        props = tools[0].inputSchema["properties"]
        assert props["timeout_seconds"]["default"] == 3600
