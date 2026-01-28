import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

try:
    import mcp  # noqa: F401
except ImportError:
    mcp_stub = ModuleType("mcp")
    server_stub = ModuleType("mcp.server")
    stdio_stub = ModuleType("mcp.server.stdio")
    types_stub = ModuleType("mcp.types")

    class Server:
        def __init__(self, name: str):
            self.name = name

        def list_tools(self):
            def decorator(fn):
                return fn

            return decorator

        def call_tool(self):
            def decorator(fn):
                return fn

            return decorator

        async def run(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def create_initialization_options(self) -> dict[str, Any]:
            return {}

    @asynccontextmanager
    async def stdio_server():
        yield (None, None)

    @dataclass
    class TextContent:
        type: str
        text: str

    @dataclass
    class Tool:
        name: str
        description: str
        inputSchema: dict[str, Any]

    server_stub.Server = Server
    stdio_stub.stdio_server = stdio_server
    types_stub.TextContent = TextContent
    types_stub.Tool = Tool

    sys.modules["mcp"] = mcp_stub
    sys.modules["mcp.server"] = server_stub
    sys.modules["mcp.server.stdio"] = stdio_stub
    sys.modules["mcp.types"] = types_stub


@pytest.fixture
def mock_popen(mocker):
    """Mock subprocess.Popen for testing without real Kimi CLI."""
    mock = mocker.patch("moonbridge.server.Popen")
    process = MagicMock()
    process.communicate.return_value = ("Hello from Kimi", "")
    process.returncode = 0
    process.pid = 12345
    mock.return_value = process
    return mock


@pytest.fixture
def mock_which_kimi(mocker):
    """Mock shutil.which to find kimi."""
    return mocker.patch("moonbridge.adapters.kimi.shutil.which", return_value="/usr/local/bin/kimi")


@pytest.fixture
def mock_which_no_kimi(mocker):
    """Mock shutil.which to NOT find kimi."""
    return mocker.patch("moonbridge.adapters.kimi.shutil.which", return_value=None)
