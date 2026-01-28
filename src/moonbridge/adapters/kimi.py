import shutil

from .base import AdapterConfig


class KimiAdapter:
    """Kimi CLI adapter."""

    config = AdapterConfig(
        name="kimi",
        cli_command="kimi",
        tool_description=(
            "Spawn a Kimi K2.5 agent in the current directory. "
            "Kimi excels at frontend development and visual coding."
        ),
        safe_env_keys=(
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
        ),
        auth_patterns=("login required", "unauthorized", "authentication failed", "401", "403"),
        auth_message="Run: kimi login",
        install_hint="uv tool install kimi-cli",
        supports_thinking=True,
    )

    def build_command(self, prompt: str, thinking: bool) -> list[str]:
        cmd = [self.config.cli_command, "--print"]
        if thinking:
            cmd.append("--thinking")
        cmd.extend(["--prompt", prompt])
        return cmd

    def check_installed(self) -> tuple[bool, str | None]:
        path = shutil.which(self.config.cli_command)
        return (path is not None, path)
