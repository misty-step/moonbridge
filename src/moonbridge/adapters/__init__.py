from .base import AdapterConfig, CLIAdapter
from .kimi import KimiAdapter

_ADAPTERS: dict[str, CLIAdapter] = {
    "kimi": KimiAdapter(),
}


def get_adapter(name: str = "kimi") -> CLIAdapter:
    """Get adapter by name. Defaults to kimi."""
    if name not in _ADAPTERS:
        raise ValueError(f"Unknown adapter: {name}")
    return _ADAPTERS[name]


def list_adapters() -> list[str]:
    """List available adapter names."""
    return list(_ADAPTERS.keys())


__all__ = ["CLIAdapter", "AdapterConfig", "get_adapter", "list_adapters"]
