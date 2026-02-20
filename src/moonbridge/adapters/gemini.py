"""Gemini CLI adapter for Moonbridge."""

import shutil

from .base import AdapterConfig, static_model_catalog


class GeminiAdapter:
    """Gemini CLI adapter."""

    config = AdapterConfig(
        name="gemini",
        cli_command="gemini",
        tool_description=(
            "Spawn a Gemini CLI agent to execute tasks. "
            "Gemini supports fast multimodal and coding workflows."
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
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION",
            "GOOGLE_GENAI_USE_VERTEXAI",
        ),
        auth_patterns=(
            "unauthorized",
            "authentication",
            "api key",
            "login required",
            "not authenticated",
            "401",
            "403",
        ),
        auth_message="Run: gemini (complete login flow) or set GEMINI_API_KEY",
        install_hint="npm install -g @google/gemini-cli",
        supports_thinking=False,
        known_models=(
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-flash",
        ),
        default_timeout=1200,
        default_model="gemini-2.5-pro",
    )

    def build_command(
        self,
        prompt: str,
        thinking: bool,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> list[str]:
        """Build Gemini CLI command."""
        _ = thinking
        _ = reasoning_effort

        cmd = [
            self.config.cli_command,
            "--approval-mode",
            "yolo",
            "--output-format",
            "text",
        ]
        if model:
            if model.startswith("-"):
                raise ValueError(f"model cannot start with '-': {model}")
            cmd.extend(["-m", model])
        cmd.extend(["-p", prompt])
        return cmd

    def check_installed(self) -> tuple[bool, str | None]:
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
