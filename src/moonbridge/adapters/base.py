from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AdapterConfig:
    """Per-adapter configuration."""

    name: str
    cli_command: str
    safe_env_keys: tuple[str, ...]
    auth_patterns: tuple[str, ...]
    auth_message: str
    install_hint: str
    supports_thinking: bool
    default_timeout: int = 600


class CLIAdapter(Protocol):
    """Protocol for CLI backend adapters."""

    config: AdapterConfig

    def build_command(self, prompt: str, thinking: bool) -> list[str]:
        """Build CLI command for execution."""
        ...

    def check_installed(self) -> tuple[bool, str | None]:
        """Check if CLI is installed. Returns (installed, path)."""
        ...
