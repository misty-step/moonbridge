import pytest

from moonbridge.adapters import CLIAdapter, get_adapter, list_adapters
from moonbridge.adapters.kimi import KimiAdapter


def test_kimi_adapter_build_command_basic():
    adapter = KimiAdapter()
    cmd = adapter.build_command("hello world", thinking=False)
    assert cmd == ["kimi", "--print", "--prompt", "hello world"]


def test_kimi_adapter_build_command_with_thinking():
    adapter = KimiAdapter()
    cmd = adapter.build_command("hello world", thinking=True)
    assert cmd == ["kimi", "--print", "--thinking", "--prompt", "hello world"]


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
    with pytest.raises(ValueError, match="Unknown adapter: nonexistent. Available: kimi"):
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
