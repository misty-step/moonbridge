# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Moonbridge

An MCP server that spawns Kimi K2.5 agents from any MCP client. Enables parallel agent execution—run 10 approaches simultaneously for the cost of one Claude request.

## Commands

```bash
# Development
uv sync                      # Install dependencies
uv sync --dev                # Install with dev dependencies

# Quality gates
ruff check src/              # Lint
mypy src/                    # Type check
pytest -v                    # Run all tests
pytest tests/test_server.py -v                    # Single test file
pytest tests/test_server.py::test_spawn_agent -v  # Single test

# Run locally
uvx moonbridge               # Run via uvx (recommended)
python -m moonbridge.server  # Direct run

# Build
uv build                     # Build package
```

## Architecture

```
src/moonbridge/
├── server.py          # MCP server implementation, tool handlers, process management
├── version_check.py   # Update notification (24h cache)
└── adapters/
    ├── base.py        # CLIAdapter protocol and AdapterConfig dataclass
    ├── kimi.py        # Kimi CLI adapter implementation
    └── __init__.py    # Adapter registry and get_adapter()
```

**Adapter pattern**: The codebase uses a protocol-based adapter pattern to support multiple CLI backends. `CLIAdapter` defines the interface; each adapter implements `build_command()` and `check_installed()`. Currently only Kimi is implemented, but the pattern exists for future backends (Claude Code CLI, Gemini CLI).

**Process lifecycle**: Agents spawn as subprocess with `start_new_session=True` for clean process group management. Orphan cleanup is registered via `atexit`. Processes are tracked via weak references in `_active_processes`.

**Environment sandboxing**: Only whitelisted env vars (`safe_env_keys`) are passed to spawned processes. Directory restrictions via `MOONBRIDGE_ALLOWED_DIRS`.

## MCP Tools Exposed

| Tool | Purpose |
|------|---------|
| `spawn_agent` | Single agent execution |
| `spawn_agents_parallel` | Up to 10 agents concurrently |
| `check_status` | Verify CLI installation and auth |

## Testing

Tests mock `Popen` and `shutil.which` to avoid requiring Kimi CLI. See `conftest.py` for fixtures:
- `mock_popen` - Mock subprocess execution
- `mock_which_kimi` - Mock Kimi CLI found
- `mock_which_no_kimi` - Mock Kimi CLI not found

The MCP library is also stubbed in conftest when not installed, enabling tests to run without the full MCP dependency.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MOONBRIDGE_ADAPTER` | `kimi` | CLI backend to use |
| `MOONBRIDGE_TIMEOUT` | `600` | Default timeout (30-3600s) |
| `MOONBRIDGE_MAX_AGENTS` | `10` | Max parallel agents |
| `MOONBRIDGE_ALLOWED_DIRS` | (none) | Colon-separated directory allowlist |
| `MOONBRIDGE_STRICT` | `false` | Exit if ALLOWED_DIRS unset |
| `MOONBRIDGE_LOG_LEVEL` | `WARNING` | Logging verbosity |

## Release Process

Uses release-please for automated releases. CI publishes to PyPI on release tags. Version is maintained in `src/moonbridge/__init__.py`.
