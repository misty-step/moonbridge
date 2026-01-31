import os

from .base import AdapterConfig, CLIAdapter
from .codex import CodexAdapter
from .kimi import KimiAdapter

ADAPTER_REGISTRY: dict[str, CLIAdapter] = {
    "kimi": KimiAdapter(),
    "codex": CodexAdapter(),
}


def get_adapter(name: str | None = None) -> CLIAdapter:
    """Get adapter by name.

    Args:
        name: Adapter name. If None, uses MOONBRIDGE_ADAPTER env var,
            falling back to "kimi" if unset or empty.
    """
    if name is None:
        name = (os.environ.get("MOONBRIDGE_ADAPTER") or "").strip() or "kimi"
    if name not in ADAPTER_REGISTRY:
        available = ", ".join(sorted(ADAPTER_REGISTRY))
        raise ValueError(f"Unknown adapter: {name}. Available: {available}")
    return ADAPTER_REGISTRY[name]


def list_adapters() -> list[str]:
    """List available adapter names."""
    return list(ADAPTER_REGISTRY.keys())


__all__ = [
    "ADAPTER_REGISTRY",
    "CLIAdapter",
    "AdapterConfig",
    "get_adapter",
    "list_adapters",
]
