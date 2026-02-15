"""OpenCode (opencode) CLI adapter for Moonbridge.

OpenCode supports many providers via a single CLI. Model selection uses the
`provider/model` form (for example: `openrouter/minimax/minimax-m2.5`).
"""

import shutil

from .base import AdapterConfig


class OpencodeAdapter:
    """OpenCode CLI adapter."""

    config = AdapterConfig(
        name="opencode",
        cli_command="opencode",
        tool_description=(
            "Spawn an OpenCode agent to execute tasks. "
            "OpenCode supports many providers; models use the 'provider/model' form "
            "(example: 'openrouter/minimax/minimax-m2.5')."
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
            # OpenCode config overrides (optional).
            "OPENCODE_CONFIG",
            "OPENCODE_CONFIG_DIR",
            "OPENCODE_CONFIG_CONTENT",
            # OpenRouter (optional): OpenCode can also store creds via `opencode auth login`.
            "OPENROUTER_API_KEY",
        ),
        auth_patterns=(
            "unauthorized",
            "authentication",
            "api key",
            "not authenticated",
            "login required",
            "401",
            "403",
        ),
        auth_message="Run: opencode auth login",
        install_hint="curl -fsSL https://opencode.ai/install | bash",
        supports_thinking=False,
        known_models=("openrouter/minimax/minimax-m2.5",),
        default_timeout=1200,  # OpenCode can run multi-step agent loops.
        default_model="openrouter/minimax/minimax-m2.5",
    )

    def build_command(
        self,
        prompt: str,
        thinking: bool,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> list[str]:
        """Build OpenCode CLI command.

        OpenCode is non-interactive via `opencode run ...`.

        Raises:
            ValueError: If model starts with '-' (flag injection prevention).
        """
        _ = thinking
        _ = reasoning_effort

        cmd = [self.config.cli_command, "run"]
        if model:
            if model.startswith("-"):
                raise ValueError(f"model cannot start with '-': {model}")
            cmd.extend(["-m", model])
        cmd.extend(["--", prompt])
        return cmd

    def check_installed(self) -> tuple[bool, str | None]:
        path = shutil.which(self.config.cli_command)
        return (path is not None, path)

