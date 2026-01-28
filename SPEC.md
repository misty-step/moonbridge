# Moonbridge - Kimi K2.5 MCP Server

## Overview

**Moonbridge** is an MCP (Model Context Protocol) server that bridges Claude Code to Kimi K2.5's Agent Swarm capability. The name connects to Moonshot AI (Kimi's creator) while capturing the bridge metaphor of MCP integration.

### What This Is
- An MCP server wrapping the Kimi CLI
- Enables Claude Code to delegate tasks to Kimi K2.5 agents
- Leverages Agent Swarm for parallel task execution (4.5x faster)

### Why It Exists
- Cost-effective delegation (~$0.15/M input vs $3/M for Claude)
- Agent Swarm coordinates up to 100 sub-agents, 1,500+ tool calls
- Kimi excels at frontend/visual coding tasks
- Open weights (Apache 2.0) with strong coding benchmarks

### Who Made It
Spun out from internal tooling at [Misty Step](https://github.com/MistyStep).

---

## Source Files

Port these files from `~/.claude/mcps/kimi-as-mcp/`:

### `pyproject.toml`
```toml
[project]
name = "kimi-as-mcp"
version = "0.1.0"
description = "MCP server for delegating tasks to Kimi K2.5 CLI agents"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "mcp>=1.0.0",
]

[project.scripts]
kimi-as-mcp = "kimi_as_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### `src/kimi_as_mcp/__init__.py`
```python
"""MCP server for delegating tasks to Kimi K2.5 CLI agents."""

__version__ = "0.1.0"
```

### `src/kimi_as_mcp/server.py`
```python
"""MCP server for spawning Kimi K2.5 agents.

Mirrors codex-as-mcp pattern: provides spawn_agent and spawn_agents_parallel
tools for delegating implementation tasks to Kimi's Agent Swarm.
"""

import asyncio
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("kimi-as-mcp")


def _run_kimi(prompt: str, thinking: bool = False, cwd: str | None = None) -> str:
    """Execute kimi CLI in non-interactive mode.

    Args:
        prompt: The task/instruction for the agent
        thinking: Enable extended reasoning mode
        cwd: Working directory (defaults to current)

    Returns:
        Agent output (stdout)
    """
    cmd = ["kimi", "--print"]
    if thinking:
        cmd.append("--thinking")
    cmd.extend(["--prompt", prompt])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or os.getcwd(),
        timeout=600,  # 10 minute timeout
    )

    output = result.stdout
    if result.returncode != 0 and result.stderr:
        output += f"\n\nSTDERR:\n{result.stderr}"

    return output


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="spawn_agent",
            description=(
                "Spawn a Kimi K2.5 agent to work in the current directory. "
                "Kimi excels at frontend development, visual coding, and "
                "can coordinate up to 100 sub-agents via Agent Swarm. "
                "Very cost-effective (~$0.15/M input, $2.50/M output)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Instructions for the agent (task, context, constraints)",
                    },
                    "thinking": {
                        "type": "boolean",
                        "description": "Enable extended reasoning mode for complex tasks",
                        "default": False,
                    },
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="spawn_agents_parallel",
            description=(
                "Spawn multiple Kimi K2.5 agents in parallel. "
                "Leverages Agent Swarm for 4.5x faster execution than sequential. "
                "Each agent runs independently in the current working directory."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agents": {
                        "type": "array",
                        "description": "List of agent specs with 'prompt' and optional 'thinking' keys",
                        "items": {
                            "type": "object",
                            "properties": {
                                "prompt": {"type": "string"},
                                "thinking": {"type": "boolean", "default": False},
                            },
                            "required": ["prompt"],
                        },
                    },
                },
                "required": ["agents"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    cwd = os.getcwd()

    if name == "spawn_agent":
        prompt = arguments["prompt"]
        thinking = arguments.get("thinking", False)

        output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_kimi(prompt, thinking, cwd)
        )

        return [TextContent(type="text", text=output)]

    elif name == "spawn_agents_parallel":
        agents = arguments["agents"]

        def run_agent(spec: dict) -> dict:
            idx = spec.get("_index", 0)
            try:
                output = _run_kimi(
                    spec["prompt"],
                    spec.get("thinking", False),
                    cwd,
                )
                return {"index": idx, "output": output}
            except Exception as e:
                return {"index": idx, "output": "", "error": str(e)}

        # Add indices for tracking
        for i, agent in enumerate(agents):
            agent["_index"] = i

        # Run in parallel with thread pool
        with ThreadPoolExecutor(max_workers=min(len(agents), 10)) as executor:
            results = list(executor.map(run_agent, agents))

        # Sort by index
        results.sort(key=lambda x: x["index"])

        # Format output
        output_parts = []
        for r in results:
            header = f"=== Agent {r['index']} ==="
            if "error" in r:
                output_parts.append(f"{header}\nERROR: {r['error']}")
            else:
                output_parts.append(f"{header}\n{r['output']}")

        return [TextContent(type="text", text="\n\n".join(output_parts))]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run():
    """Run the MCP server with stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Entry point."""
    import asyncio

    asyncio.run(run())


if __name__ == "__main__":
    main()
```

---

## Required Transformations

When porting, apply these changes:

### 1. Rename Package
- `kimi-as-mcp` → `moonbridge`
- `kimi_as_mcp` → `moonbridge`
- Entry point: `moonbridge = "moonbridge.server:main"`
- Server name: `Server("moonbridge")`

### 2. Update `pyproject.toml`
```toml
[project]
name = "moonbridge"
version = "0.1.0"
description = "MCP server bridging Claude Code to Kimi K2.5 Agent Swarm"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [
    { name = "Misty Step", email = "hello@mistystep.com" }
]
keywords = ["mcp", "kimi", "agent", "ai", "automation", "cli", "moonshot"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = [
    "mcp>=1.0.0",
]

[project.urls]
Homepage = "https://github.com/MistyStep/moonbridge"
Documentation = "https://github.com/MistyStep/moonbridge#readme"
Repository = "https://github.com/MistyStep/moonbridge"
Issues = "https://github.com/MistyStep/moonbridge/issues"

[project.scripts]
moonbridge = "moonbridge.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## Files to Create

### `LICENSE`
```
MIT License

Copyright (c) 2025 Misty Step

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### `README.md`
```markdown
# Moonbridge

[![PyPI version](https://badge.fury.io/py/moonbridge.svg)](https://badge.fury.io/py/moonbridge)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

MCP server bridging Claude Code to Kimi K2.5 Agent Swarm.

## What is this?

Moonbridge is an [MCP](https://modelcontextprotocol.io/) server that lets Claude Code delegate tasks to [Kimi K2.5](https://kimi.ai/) agents. The name connects to Moonshot AI (Kimi's creator) while capturing the bridge metaphor.

**Why use Kimi via Claude Code?**
- **Agent Swarm**: Kimi can coordinate up to 100 sub-agents with 1,500+ tool calls
- **Cost-effective**: ~$0.15/M input tokens vs $3/M for Claude
- **Frontend excellence**: Best open-source model for visual/UI coding
- **Parallel execution**: 4.5x faster than sequential with `spawn_agents_parallel`

## Installation

```bash
# Install from PyPI
pip install moonbridge

# Or use directly with uvx
uvx moonbridge
```

## Prerequisites

1. **Install Kimi CLI**:
   ```bash
   uv tool install --python 3.13 kimi-cli
   ```

2. **Authenticate** (one-time setup):
   ```bash
   kimi login
   ```
   Opens browser for Moonshot account OAuth.

3. **Verify**:
   ```bash
   kimi --print --prompt "Say hello"
   ```

## MCP Configuration

Add to your Claude Code `.mcp.json`:

```json
{
  "mcpServers": {
    "kimi": {
      "type": "stdio",
      "command": "uvx",
      "args": ["moonbridge"]
    }
  }
}
```

Or if installed globally:

```json
{
  "mcpServers": {
    "kimi": {
      "type": "stdio",
      "command": "moonbridge"
    }
  }
}
```

## Tools

### `spawn_agent`

Spawn a single Kimi agent in the current working directory.

```json
{
  "prompt": "Create a React component for user authentication",
  "thinking": false
}
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `prompt` | string | Instructions for the agent |
| `thinking` | boolean | Enable extended reasoning mode (default: false) |

### `spawn_agents_parallel`

Spawn multiple agents in parallel, leveraging Agent Swarm.

```json
{
  "agents": [
    {"prompt": "Write unit tests for auth.ts"},
    {"prompt": "Write integration tests for auth flow", "thinking": true}
  ]
}
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `agents` | array | List of agent specs with `prompt` and optional `thinking` |

## When to Use Kimi vs Other Agents

| Task Type | Recommended |
|-----------|-------------|
| Standard implementation | Codex |
| Budget-conscious work | **Kimi** |
| Frontend/visual coding | **Kimi** |
| Complex multi-step | **Kimi** (Agent Swarm) |
| Git-heavy workflows | Codex |
| Research tasks | Gemini |

## Kimi K2.5 Capabilities

- **Agent Swarm**: Coordinates up to 100 sub-agents
- **Multimodal**: Text, images, video from single prompt
- **Open weights**: Apache 2.0 license
- **Benchmarks**: Competitive with GPT-4o and Claude 3.5 on coding tasks

## License

MIT - see [LICENSE](LICENSE)

## Credits

- Built by [Misty Step](https://github.com/MistyStep)
- Powered by [Kimi K2.5](https://kimi.ai/) from Moonshot AI
- Uses the [Model Context Protocol](https://modelcontextprotocol.io/)
```

### `CONTRIBUTING.md`
```markdown
# Contributing to Moonbridge

Thank you for considering contributing!

## Development Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/MistyStep/moonbridge.git
   cd moonbridge
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   ```

3. Install in editable mode:
   ```bash
   pip install -e ".[dev]"
   ```

4. Install Kimi CLI and authenticate:
   ```bash
   uv tool install --python 3.13 kimi-cli
   kimi login
   ```

## Running Tests

```bash
pytest
```

## Code Style

- Use `ruff` for linting and formatting
- Type hints required for all public functions
- Docstrings for all public modules, classes, and functions

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and linting
5. Commit with clear messages
6. Push and open a PR

## Reporting Issues

Open an issue at https://github.com/MistyStep/moonbridge/issues
```

### `.github/workflows/publish.yml`
```yaml
name: Publish to PyPI

on:
  release:
    types: [published]
  workflow_dispatch:

jobs:
  publish:
    runs-on: ubuntu-latest
    environment: release
    permissions:
      id-token: write  # For trusted publishing

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install build tools
        run: pip install build

      - name: Build package
        run: python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

### `.github/workflows/test.yml`
```yaml
name: Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"

      - name: Run tests
        run: pytest -v

      - name: Type check
        run: mypy src/

      - name: Lint
        run: ruff check src/
```

### `tests/test_server.py`
```python
"""Basic smoke tests for moonbridge."""

import pytest
from moonbridge.server import list_tools, server


@pytest.mark.asyncio
async def test_list_tools_returns_two_tools():
    """Verify both tools are registered."""
    tools = await list_tools()
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert names == {"spawn_agent", "spawn_agents_parallel"}


@pytest.mark.asyncio
async def test_spawn_agent_schema():
    """Verify spawn_agent has correct schema."""
    tools = await list_tools()
    spawn_agent = next(t for t in tools if t.name == "spawn_agent")

    schema = spawn_agent.inputSchema
    assert schema["type"] == "object"
    assert "prompt" in schema["properties"]
    assert "thinking" in schema["properties"]
    assert schema["required"] == ["prompt"]


@pytest.mark.asyncio
async def test_spawn_agents_parallel_schema():
    """Verify spawn_agents_parallel has correct schema."""
    tools = await list_tools()
    parallel = next(t for t in tools if t.name == "spawn_agents_parallel")

    schema = parallel.inputSchema
    assert schema["type"] == "object"
    assert "agents" in schema["properties"]
    assert schema["properties"]["agents"]["type"] == "array"
    assert schema["required"] == ["agents"]


def test_server_name():
    """Verify server has correct name."""
    assert server.name == "moonbridge"
```

### Update `pyproject.toml` with dev dependencies
```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "mypy>=1.0",
    "ruff>=0.1",
]
```

---

## Directory Structure

Final repository structure:

```
moonbridge/
├── .github/
│   └── workflows/
│       ├── publish.yml
│       └── test.yml
├── src/
│   └── moonbridge/
│       ├── __init__.py
│       └── server.py
├── tests/
│   └── test_server.py
├── .gitignore
├── CONTRIBUTING.md
├── LICENSE
├── pyproject.toml
└── README.md
```

### `.gitignore`
```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
.venv/
venv/
ENV/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Testing
.pytest_cache/
.coverage
htmlcov/

# Type checking
.mypy_cache/

# Build
*.whl
```

---

## Repository Setup Checklist

1. [ ] Create repo at https://github.com/MistyStep/moonbridge
2. [ ] Set visibility to Public
3. [ ] Add description: "MCP server bridging Claude Code to Kimi K2.5 Agent Swarm"
4. [ ] Add topics: `mcp`, `kimi`, `agent`, `ai`, `automation`, `cli`, `moonshot-ai`
5. [ ] Enable GitHub Actions
6. [ ] Configure PyPI trusted publishing (Settings → Environments → release)

---

## PyPI Publishing

### Package Details
- **Name**: `moonbridge`
- **Install**: `pip install moonbridge` or `uvx moonbridge`
- **Entry point**: `moonbridge` command

### First Release
1. Create GitHub release with tag `v0.1.0`
2. Workflow auto-publishes to PyPI via trusted publishing
3. Verify: `pip install moonbridge && moonbridge --help`

---

## Verification Checklist

After implementation, verify:

- [ ] `uvx moonbridge` starts server without error
- [ ] MCP client can connect and list tools
- [ ] `spawn_agent` executes Kimi task successfully
- [ ] `spawn_agents_parallel` runs multiple tasks
- [ ] README renders correctly on GitHub
- [ ] PyPI page has correct metadata
- [ ] Tests pass on Python 3.11, 3.12, 3.13
- [ ] Type checking passes with mypy
- [ ] Linting passes with ruff

---

## Future Enhancements (out of scope for v0.1.0)

- [ ] Configurable timeout via environment variable
- [ ] Working directory override parameter
- [ ] Streaming output support
- [ ] Agent status/progress callbacks
- [ ] Custom Kimi model selection
