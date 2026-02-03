from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterConfig:
    """Per-adapter configuration."""

    name: str
    cli_command: str
    tool_description: str
    safe_env_keys: tuple[str, ...]
    auth_patterns: tuple[str, ...]
    auth_message: str
    install_hint: str
    supports_thinking: bool
    known_models: tuple[str, ...] = ()  # Known model options for this adapter
    default_timeout: int = 600


@dataclass(frozen=True)
class AgentResult:
    """Agent execution result."""

    status: str
    output: str
    stderr: str | None
    returncode: int
    duration_ms: int
    agent_index: int
    message: str | None = None
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "output": self.output,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "duration_ms": self.duration_ms,
            "agent_index": self.agent_index,
        }
        if self.message is not None:
            payload["message"] = self.message
        if self.raw is not None:
            payload["raw"] = self.raw
        return payload


class CLIAdapter(Protocol):
    """Protocol for CLI backend adapters."""

    config: AdapterConfig

    def build_command(
        self,
        prompt: str,
        thinking: bool,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> list[str]:
        """Build CLI command for execution."""
        ...

    def check_installed(self) -> tuple[bool, str | None]:
        """Check if CLI is installed. Returns (installed, path)."""
        ...
