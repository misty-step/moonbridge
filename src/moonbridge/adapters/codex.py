"""Codex CLI adapter for Moonbridge."""

import shutil

from .base import AdapterConfig


class CodexAdapter:
    """Codex CLI adapter."""

    config = AdapterConfig(
        name="codex",
        cli_command="codex",
        tool_description=(
            "Spawn a Codex agent to execute tasks. "
            "Codex excels at code implementation and automated development workflows."
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
            "OPENAI_API_KEY",
        ),
        auth_patterns=(
            "unauthorized",
            "authentication",
            "api key",
            "invalid key",
            "not logged in",
            "401",
            "403",
        ),
        auth_message="Run: codex login",
        install_hint="See https://github.com/openai/codex",
        supports_thinking=False,
    )

    def build_command(self, prompt: str, thinking: bool, model: str | None = None) -> list[str]:
        """Build Codex CLI command.

        Args:
            prompt: Task prompt for the agent.
            thinking: Ignored - Codex doesn't support thinking mode.
                      Validation happens in server.py.
            model: Model to use (e.g., 'gpt-5.2-codex-high'). Optional.

        Returns:
            Command list: ["codex", "exec", "--skip-git-repo-check", "--full-auto", ...]
        """
        cmd = [self.config.cli_command, "exec", "--skip-git-repo-check", "--full-auto"]
        if model:
            cmd.extend(["-m", model])
        cmd.append(prompt)
        return cmd

    def check_installed(self) -> tuple[bool, str | None]:
        """Check if Codex CLI is installed."""
        path = shutil.which(self.config.cli_command)
        return (path is not None, path)
