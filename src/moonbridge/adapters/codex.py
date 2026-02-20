"""Codex CLI adapter for Moonbridge."""

import shutil

from .base import AdapterConfig, static_model_catalog

REASONING_EFFORTS = ("low", "medium", "high", "xhigh")


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
        known_models=(
            "gpt-5.3-codex",
            "gpt-5.2-codex",
            "gpt-5.1-codex",
            "gpt-5.1-codex-mini",
            "gpt-5.1-codex-max",
        ),
        default_timeout=1800,  # 30 minutes - Codex runs long
        default_model="gpt-5.3-codex",
        default_reasoning_effort="xhigh",
    )

    def build_command(
        self,
        prompt: str,
        thinking: bool,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> list[str]:
        """Build Codex CLI command.

        Args:
            prompt: Task prompt for the agent.
            thinking: Ignored - Codex doesn't support thinking mode.
                      Validation happens in server.py.
            model: Model to use (e.g., 'gpt-5.2-codex'). Optional.
            reasoning_effort: Reasoning effort level (low, medium, high, xhigh). Optional.

        Returns:
            Command list: ["codex", "exec", "--skip-git-repo-check", "--full-auto", ...]

        Raises:
            ValueError: If model starts with '-' (flag injection prevention).
        """
        cmd = [self.config.cli_command, "exec", "--skip-git-repo-check", "--full-auto"]
        if model:
            if model.startswith("-"):
                raise ValueError(f"model cannot start with '-': {model}")
            cmd.extend(["-m", model])
        if reasoning_effort and reasoning_effort in REASONING_EFFORTS:
            cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
        cmd.extend(["--", prompt])
        return cmd

    def check_installed(self) -> tuple[bool, str | None]:
        """Check if Codex CLI is installed."""
        path = shutil.which(self.config.cli_command)
        return (path is not None, path)

    def list_models(
        self,
        cwd: str,
        provider: str | None = None,
        refresh: bool = False,
        timeout_seconds: int = 30,
    ) -> tuple[list[str], str]:
        return static_model_catalog(self.config)
