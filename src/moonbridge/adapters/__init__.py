import os

from .base import AdapterConfig, CLIAdapter
from .kimi import KimiAdapter

_ADAPTERS: dict[str, CLIAdapter] = {
    "kimi": KimiAdapter(),
}


def get_adapter(name: str | None = None) -> CLIAdapter:
    """Get adapter by name.

    Args:
        name: Adapter name. If None, uses MOONBRIDGE_ADAPTER env var,
            falling back to "kimi" if unset or empty.
    """
    if name is None:
        name = (os.environ.get("MOONBRIDGE_ADAPTER") or "").strip() or "kimi"
    if name not in _ADAPTERS:
        available = ", ".join(sorted(_ADAPTERS))
        raise ValueError(f"Unknown adapter: {name}. Available: {available}")
    return _ADAPTERS[name]


def list_adapters() -> list[str]:
    """List available adapter names."""
    return list(_ADAPTERS.keys())


__all__ = ["CLIAdapter", "AdapterConfig", "get_adapter", "list_adapters"]
