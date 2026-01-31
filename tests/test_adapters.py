import pytest

from moonbridge.adapters import CLIAdapter, get_adapter, list_adapters
from moonbridge.adapters.codex import CodexAdapter
from moonbridge.adapters.kimi import KimiAdapter


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
