import pytest

from moonbridge.adapters import CLIAdapter, get_adapter, list_adapters
from moonbridge.adapters.base import AgentResult, static_model_catalog
from moonbridge.adapters.codex import CodexAdapter
from moonbridge.adapters.gemini import GeminiAdapter
from moonbridge.adapters.kimi import KimiAdapter
from moonbridge.adapters.opencode import OpencodeAdapter

# AgentResult tests


class TestAgentResultToDict:
    """Unit tests for AgentResult.to_dict() method."""

    def test_base_fields_only(self) -> None:
        """to_dict includes all required fields, omits None optionals."""
        result = AgentResult(
            status="success",
            output="test output",
            stderr=None,
            returncode=0,
            duration_ms=100,
            agent_index=0,
        )
        d = result.to_dict()

        assert d == {
            "status": "success",
            "output": "test output",
            "stderr": None,
            "returncode": 0,
            "duration_ms": 100,
            "agent_index": 0,
        }
        assert "message" not in d
        assert "raw" not in d

    def test_with_message(self) -> None:
        """to_dict includes message when set."""
        result = AgentResult(
            status="auth_error",
            output="",
            stderr="auth failed",
            returncode=1,
            duration_ms=50,
            agent_index=0,
            message="Run: kimi login",
        )
        d = result.to_dict()

        assert d["message"] == "Run: kimi login"
        assert "raw" not in d

    def test_with_raw(self) -> None:
        """to_dict includes raw when set."""
        raw_data = {"tokens": 150, "model": "gpt-5"}
        result = AgentResult(
            status="success",
            output="output",
            stderr=None,
            returncode=0,
            duration_ms=100,
            agent_index=1,
            raw=raw_data,
        )
        d = result.to_dict()

        assert d["raw"] == raw_data
        assert "message" not in d

    def test_with_both_optional_fields(self) -> None:
        """to_dict includes both message and raw when both set."""
        result = AgentResult(
            status="error",
            output="",
            stderr="error details",
            returncode=1,
            duration_ms=200,
            agent_index=2,
            message="Custom error",
            raw={"debug": "info"},
        )
        d = result.to_dict()

        assert d["message"] == "Custom error"
        assert d["raw"] == {"debug": "info"}


class TestAgentResultImmutability:
    """Tests for AgentResult frozen dataclass behavior."""

    def test_cannot_modify_fields(self) -> None:
        """AgentResult fields cannot be reassigned after construction."""
        result = AgentResult(
            status="success",
            output="test",
            stderr=None,
            returncode=0,
            duration_ms=100,
            agent_index=0,
        )
        with pytest.raises(AttributeError):
            result.status = "error"  # type: ignore[misc]


def test_kimi_adapter_build_command_basic():
    adapter = KimiAdapter()
    cmd = adapter.build_command("hello world", thinking=False)
    assert cmd == ["kimi", "--print", "--prompt", "hello world"]


def test_kimi_adapter_build_command_with_thinking():
    adapter = KimiAdapter()
    cmd = adapter.build_command("hello world", thinking=True)
    assert cmd == ["kimi", "--print", "--thinking", "--prompt", "hello world"]


def test_kimi_adapter_build_command_with_model():
    adapter = KimiAdapter()
    cmd = adapter.build_command("hello world", thinking=False, model="kimi-k2.5")
    assert cmd == ["kimi", "--print", "-m", "kimi-k2.5", "--prompt", "hello world"]


def test_kimi_adapter_build_command_with_thinking_and_model():
    adapter = KimiAdapter()
    cmd = adapter.build_command("hello world", thinking=True, model="kimi-k2.5")
    assert cmd == [
        "kimi",
        "--print",
        "--thinking",
        "-m",
        "kimi-k2.5",
        "--prompt",
        "hello world",
    ]


def test_kimi_adapter_check_installed(mocker):
    mocker.patch("shutil.which", return_value="/usr/local/bin/kimi")
    adapter = KimiAdapter()
    installed, path = adapter.check_installed()
    assert installed is True
    assert path == "/usr/local/bin/kimi"


def test_kimi_adapter_check_not_installed(mocker):
    mocker.patch("shutil.which", return_value=None)
    adapter = KimiAdapter()
    installed, path = adapter.check_installed()
    assert installed is False
    assert path is None


def test_get_adapter_default(monkeypatch):
    monkeypatch.delenv("MOONBRIDGE_ADAPTER", raising=False)
    adapter: CLIAdapter = get_adapter()
    assert adapter.config.name == "kimi"


def test_get_adapter_env_override(monkeypatch):
    monkeypatch.setenv("MOONBRIDGE_ADAPTER", "kimi")
    adapter = get_adapter()
    assert isinstance(adapter, KimiAdapter)


def test_get_adapter_env_invalid_raises(monkeypatch):
    monkeypatch.setenv("MOONBRIDGE_ADAPTER", "nonexistent")
    with pytest.raises(ValueError, match="Unknown adapter: nonexistent. Available:"):
        get_adapter()


def test_get_adapter_explicit_name_overrides_env(monkeypatch):
    """Explicit name parameter takes precedence over env var."""
    monkeypatch.setenv("MOONBRIDGE_ADAPTER", "nonexistent")
    adapter = get_adapter("kimi")
    assert adapter.config.name == "kimi"


def test_get_adapter_env_whitespace_falls_back_to_default(monkeypatch):
    """Whitespace-only env var falls back to default."""
    monkeypatch.setenv("MOONBRIDGE_ADAPTER", "  ")
    adapter = get_adapter()
    assert adapter.config.name == "kimi"


def test_get_adapter_by_name():
    adapter = get_adapter("kimi")
    assert isinstance(adapter, KimiAdapter)


def test_get_adapter_unknown_raises():
    with pytest.raises(ValueError, match="Unknown adapter.*Available:"):
        get_adapter("nonexistent")


def test_list_adapters():
    adapters = list_adapters()
    assert "kimi" in adapters
    assert "codex" in adapters
    assert "opencode" in adapters
    assert "gemini" in adapters


def test_kimi_adapter_config_values():
    adapter = KimiAdapter()
    assert adapter.config.cli_command == "kimi"
    assert adapter.config.auth_message == "Run: kimi login"
    assert adapter.config.supports_thinking is True
    assert "PATH" in adapter.config.safe_env_keys
    assert "Kimi" in adapter.config.tool_description


# Codex adapter tests


def test_codex_adapter_build_command_basic():
    adapter = CodexAdapter()
    cmd = adapter.build_command("hello world", thinking=False)
    assert cmd == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--full-auto",
        "--",
        "hello world",
    ]


def test_codex_adapter_build_command_thinking_ignored():
    """thinking param is passed but ignored (supports_thinking=False)."""
    adapter = CodexAdapter()
    cmd = adapter.build_command("test prompt", thinking=True)
    # Same command - thinking validation happens in server.py
    assert cmd == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--full-auto",
        "--",
        "test prompt",
    ]


def test_codex_adapter_build_command_with_model():
    adapter = CodexAdapter()
    cmd = adapter.build_command("hello world", thinking=False, model="gpt-5.2-codex-high")
    assert cmd == [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--full-auto",
        "-m",
        "gpt-5.2-codex-high",
        "--",
        "hello world",
    ]


def test_adapter_prompt_flag_injection_guard():
    """Verify prompts starting with '-' are handled safely."""
    prompt = "-n --help"
    # Codex uses positional arg - needs '--' to prevent flag parsing
    codex_cmd = CodexAdapter().build_command(prompt, thinking=False)
    assert codex_cmd[-2:] == ["--", prompt]

    # Kimi uses --prompt flag - prompt is value, inherently protected
    kimi_cmd = KimiAdapter().build_command(prompt, thinking=False)
    assert kimi_cmd[-2:] == ["--prompt", prompt]


def test_codex_adapter_check_installed(mocker):
    mocker.patch("moonbridge.adapters.codex.shutil.which", return_value="/usr/local/bin/codex")
    adapter = CodexAdapter()
    installed, path = adapter.check_installed()
    assert installed is True
    assert path == "/usr/local/bin/codex"


def test_codex_adapter_check_not_installed(mocker):
    mocker.patch("moonbridge.adapters.codex.shutil.which", return_value=None)
    adapter = CodexAdapter()
    installed, path = adapter.check_installed()
    assert installed is False
    assert path is None


def test_codex_adapter_config_values():
    adapter = CodexAdapter()
    assert adapter.config.name == "codex"
    assert adapter.config.cli_command == "codex"
    assert adapter.config.supports_thinking is False
    assert adapter.config.default_model == "gpt-5.3-codex"
    assert adapter.config.default_reasoning_effort == "xhigh"
    assert "OPENAI_API_KEY" in adapter.config.safe_env_keys
    assert "Codex" in adapter.config.tool_description


def test_get_adapter_codex(monkeypatch):
    monkeypatch.setenv("MOONBRIDGE_ADAPTER", "codex")
    adapter = get_adapter()
    assert adapter.config.name == "codex"


def test_get_adapter_codex_by_name():
    adapter = get_adapter("codex")
    assert isinstance(adapter, CodexAdapter)


def test_list_adapters_includes_codex():
    adapters = list_adapters()
    assert "codex" in adapters
    assert "kimi" in adapters
    assert "opencode" in adapters
    assert "gemini" in adapters


# OpenCode adapter tests


def test_opencode_adapter_build_command_basic():
    adapter = OpencodeAdapter()
    cmd = adapter.build_command("hello world", thinking=False)
    assert cmd == ["opencode", "run", "--", "hello world"]


def test_opencode_adapter_build_command_with_model():
    adapter = OpencodeAdapter()
    cmd = adapter.build_command(
        "hello world",
        thinking=False,
        model="openrouter/minimax/minimax-m2.5",
    )
    assert cmd == [
        "opencode",
        "run",
        "-m",
        "openrouter/minimax/minimax-m2.5",
        "--",
        "hello world",
    ]


def test_opencode_adapter_check_installed(mocker):
    mocker.patch(
        "moonbridge.adapters.opencode.shutil.which", return_value="/usr/local/bin/opencode"
    )
    adapter = OpencodeAdapter()
    installed, path = adapter.check_installed()
    assert installed is True
    assert path == "/usr/local/bin/opencode"


def test_opencode_adapter_check_not_installed(mocker):
    mocker.patch("moonbridge.adapters.opencode.shutil.which", return_value=None)
    adapter = OpencodeAdapter()
    installed, path = adapter.check_installed()
    assert installed is False
    assert path is None


def test_opencode_adapter_config_values():
    adapter = OpencodeAdapter()
    assert adapter.config.name == "opencode"
    assert adapter.config.cli_command == "opencode"
    assert adapter.config.supports_thinking is False
    assert adapter.config.default_model == "openrouter/minimax/minimax-m2.5"
    assert "OPENROUTER_API_KEY" in adapter.config.safe_env_keys
    assert "OpenCode" in adapter.config.tool_description


def test_opencode_adapter_rejects_model_starting_with_dash():
    adapter = OpencodeAdapter()
    with pytest.raises(ValueError, match="model cannot start with"):
        adapter.build_command("hello", thinking=False, model="--help")


def test_opencode_adapter_list_models_dynamic(mocker):
    adapter = OpencodeAdapter()
    completed = mocker.Mock()
    completed.returncode = 0
    completed.stdout = "openrouter/gpt-5\nopenrouter/gpt-5-mini\n"
    completed.stderr = ""
    mock_run = mocker.patch("moonbridge.adapters.opencode.run", return_value=completed)

    models, source = adapter.list_models(
        ".",
        provider="openrouter",
        refresh=True,
        timeout_seconds=10,
    )

    assert source == "dynamic"
    assert models == ["openrouter/gpt-5", "openrouter/gpt-5-mini"]
    mock_run.assert_called_once()


def test_opencode_adapter_list_models_raises_on_failure(mocker):
    adapter = OpencodeAdapter()
    completed = mocker.Mock()
    completed.returncode = 1
    completed.stdout = ""
    completed.stderr = "boom"
    mocker.patch("moonbridge.adapters.opencode.run", return_value=completed)

    with pytest.raises(RuntimeError, match="opencode models failed"):
        adapter.list_models(".", timeout_seconds=10)


# Gemini adapter tests


def test_gemini_adapter_build_command_basic():
    adapter = GeminiAdapter()
    cmd = adapter.build_command("hello world", thinking=False)
    assert cmd == [
        "gemini",
        "--approval-mode",
        "yolo",
        "--output-format",
        "text",
        "-p",
        "hello world",
    ]


def test_gemini_adapter_build_command_with_model():
    adapter = GeminiAdapter()
    cmd = adapter.build_command("hello world", thinking=False, model="gemini-2.5-pro")
    assert cmd == [
        "gemini",
        "--approval-mode",
        "yolo",
        "--output-format",
        "text",
        "-m",
        "gemini-2.5-pro",
        "-p",
        "hello world",
    ]


def test_gemini_adapter_check_installed(mock_which_gemini):
    adapter = GeminiAdapter()
    installed, path = adapter.check_installed()
    assert installed is True
    assert path == "/usr/local/bin/gemini"


def test_gemini_adapter_check_not_installed(mock_which_no_gemini):
    adapter = GeminiAdapter()
    installed, path = adapter.check_installed()
    assert installed is False
    assert path is None


def test_gemini_adapter_config_values():
    adapter = GeminiAdapter()
    assert adapter.config.name == "gemini"
    assert adapter.config.cli_command == "gemini"
    assert adapter.config.supports_thinking is False
    assert adapter.config.default_model == "gemini-2.5-pro"
    assert "GEMINI_API_KEY" in adapter.config.safe_env_keys
    assert "Gemini" in adapter.config.tool_description


def test_gemini_adapter_rejects_model_starting_with_dash():
    adapter = GeminiAdapter()
    with pytest.raises(ValueError, match="model cannot start with"):
        adapter.build_command("hello", thinking=False, model="--help")


# Model validation tests (flag injection prevention)


def test_kimi_adapter_rejects_model_starting_with_dash():
    """Model starting with '-' could inject flags - must be rejected."""
    adapter = KimiAdapter()
    with pytest.raises(ValueError, match="model cannot start with"):
        adapter.build_command("hello", thinking=False, model="--help")


def test_kimi_adapter_rejects_model_with_flag_pattern():
    """Model that looks like a flag must be rejected."""
    adapter = KimiAdapter()
    with pytest.raises(ValueError, match="model cannot start with"):
        adapter.build_command("hello", thinking=False, model="-m")


def test_codex_adapter_rejects_model_starting_with_dash():
    """Model starting with '-' could inject flags - must be rejected."""
    adapter = CodexAdapter()
    with pytest.raises(ValueError, match="model cannot start with"):
        adapter.build_command("hello", thinking=False, model="--dangerous")


def test_codex_adapter_rejects_model_with_flag_pattern():
    """Model that looks like a flag must be rejected."""
    adapter = CodexAdapter()
    with pytest.raises(ValueError, match="model cannot start with"):
        adapter.build_command("hello", thinking=False, model="-c")


# static_model_catalog helper tests


def test_static_model_catalog_returns_known_models():
    """Helper returns config's known_models as a list with source 'static'."""
    adapter = KimiAdapter()
    models, source = static_model_catalog(adapter.config)
    assert source == "static"
    assert models == list(adapter.config.known_models)


def test_static_model_catalog_returns_fresh_list():
    """Each call returns a new list (not a reference to the config tuple)."""
    adapter = CodexAdapter()
    a, _ = static_model_catalog(adapter.config)
    b, _ = static_model_catalog(adapter.config)
    assert a == b
    assert a is not b


# list_models consistency across adapters


def test_all_static_adapters_return_static_source():
    """kimi, codex, gemini all report source='static'."""
    for cls in (KimiAdapter, CodexAdapter, GeminiAdapter):
        adapter = cls()
        _, source = adapter.list_models(".")
        assert source == "static", f"{adapter.config.name} should return 'static'"


def test_gemini_list_models_returns_known_models():
    """Gemini list_models returns all configured known_models."""
    adapter = GeminiAdapter()
    models, _ = adapter.list_models(".")
    assert set(models) == {"gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"}


# supports_provider_filter config flag


def test_opencode_supports_provider_filter():
    adapter = OpencodeAdapter()
    assert adapter.config.supports_provider_filter is True


def test_kimi_does_not_support_provider_filter():
    adapter = KimiAdapter()
    assert adapter.config.supports_provider_filter is False


def test_codex_does_not_support_provider_filter():
    adapter = CodexAdapter()
    assert adapter.config.supports_provider_filter is False


def test_gemini_does_not_support_provider_filter():
    adapter = GeminiAdapter()
    assert adapter.config.supports_provider_filter is False


# OpenCode list_models edge cases


def test_opencode_list_models_strips_ansi_escapes(mocker):
    """ANSI escape codes in CLI output are stripped."""
    adapter = OpencodeAdapter()
    completed = mocker.Mock()
    completed.returncode = 0
    completed.stdout = "\x1B[32mopenrouter/gpt-5\x1B[0m\n\x1B[33mopenrouter/gpt-5-mini\x1B[0m\n"
    completed.stderr = ""
    mocker.patch("moonbridge.adapters.opencode.run", return_value=completed)

    models, source = adapter.list_models(".", timeout_seconds=10)

    assert source == "dynamic"
    assert models == ["openrouter/gpt-5", "openrouter/gpt-5-mini"]


def test_opencode_list_models_skips_usage_lines(mocker):
    """Lines starting with 'Usage:' are filtered out."""
    adapter = OpencodeAdapter()
    completed = mocker.Mock()
    completed.returncode = 0
    completed.stdout = "Usage: opencode models [provider]\nopenrouter/gpt-5\n"
    completed.stderr = ""
    mocker.patch("moonbridge.adapters.opencode.run", return_value=completed)

    models, _ = adapter.list_models(".", timeout_seconds=10)

    assert models == ["openrouter/gpt-5"]


def test_opencode_list_models_rejects_provider_starting_with_dash():
    """Provider starting with '-' is rejected (flag injection prevention)."""
    adapter = OpencodeAdapter()
    with pytest.raises(ValueError, match="provider cannot start with"):
        adapter.list_models(".", provider="--help")


def test_opencode_list_models_raises_on_empty_output(mocker):
    """Empty model output (after filtering) raises RuntimeError."""
    adapter = OpencodeAdapter()
    completed = mocker.Mock()
    completed.returncode = 0
    completed.stdout = "\n\n"
    completed.stderr = ""
    mocker.patch("moonbridge.adapters.opencode.run", return_value=completed)

    with pytest.raises(RuntimeError, match="opencode models returned no models"):
        adapter.list_models(".", timeout_seconds=10)
