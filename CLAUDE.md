# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Moonbridge

An MCP server that spawns AI coding agents from any MCP client. Supports multiple backends (Kimi, Codex) with parallel execution—run 10 approaches simultaneously for a fraction of the cost.

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
├── sandbox.py         # Copy-on-run sandbox + diff utilities
├── version_check.py   # Update notification (24h cache)
└── adapters/
    ├── base.py        # CLIAdapter protocol and AdapterConfig dataclass
    ├── kimi.py        # Kimi CLI adapter implementation
    ├── codex.py       # Codex CLI adapter implementation
    └── __init__.py    # Adapter registry and get_adapter()
```

**Adapter pattern**: The codebase uses a protocol-based adapter pattern to support multiple CLI backends. `CLIAdapter` defines the interface; each adapter implements `build_command()` and `check_installed()`. Currently Kimi and Codex are implemented.

**Process lifecycle**: Agents spawn as subprocess with `start_new_session=True` for clean process group management. Orphan cleanup is registered via `atexit`. Processes are tracked via weak references in `_active_processes`.

**Environment sandboxing**: Only whitelisted env vars (`safe_env_keys`) are passed to spawned processes. Directory restrictions via `MOONBRIDGE_ALLOWED_DIRS`.

## MCP Tools Exposed

| Tool | Purpose |
|------|---------|
| `spawn_agent` | Single agent execution |
| `spawn_agents_parallel` | Up to 10 agents concurrently |
| `list_adapters` | List available adapters and their status |
| `check_status` | Verify CLI installation and auth |

### Tool Parameters

Both `spawn_agent` and `spawn_agents_parallel` support:
- `adapter`: Backend to use (`kimi`, `codex`)
- `model`: Model name (e.g., `gpt-5.2-codex`, `kimi-k2.5`)
- `thinking`: Enable extended reasoning (Kimi only)
- `reasoning_effort`: Reasoning budget for Codex (`low`, `medium`, `high`, `xhigh`)
- `timeout_seconds`: Max execution time (30-3600s)

## Testing

Tests mock `Popen` and `shutil.which` to avoid requiring Kimi CLI. See `conftest.py` for fixtures:
- `mock_popen` - Mock subprocess execution
- `mock_which_kimi` - Mock Kimi CLI found
- `mock_which_no_kimi` - Mock Kimi CLI not found

The MCP library is also stubbed in conftest when not installed, enabling tests to run without the full MCP dependency.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MOONBRIDGE_ADAPTER` | `kimi` | CLI backend to use (`kimi`, `codex`) |
| `MOONBRIDGE_TIMEOUT` | `600` | Global timeout fallback (30-3600s) |
| `MOONBRIDGE_CODEX_TIMEOUT` | `1800` | Codex-specific timeout (30min default) |
| `MOONBRIDGE_KIMI_TIMEOUT` | `600` | Kimi-specific timeout (10min default) |
| `MOONBRIDGE_MAX_AGENTS` | `10` | Max parallel agents |
| `MOONBRIDGE_ALLOWED_DIRS` | (none) | Colon-separated directory allowlist |
| `MOONBRIDGE_STRICT` | `false` | Exit if ALLOWED_DIRS unset |
| `MOONBRIDGE_LOG_LEVEL` | `WARNING` | Logging verbosity |
| `MOONBRIDGE_MODEL` | (none) | Global default model for all adapters |
| `MOONBRIDGE_KIMI_MODEL` | (none) | Kimi-specific model override |
| `MOONBRIDGE_CODEX_MODEL` | (none) | Codex-specific model override (default model: `gpt-5.3-codex`) |

Timeout resolution order: tool param > adapter env var > adapter default > global env var > 600s.

Model resolution order: tool param > adapter env var > global env var > adapter default > CLI default.

Reasoning effort resolution order: tool param > adapter default (`codex` = `xhigh`).

All model values are validated: whitespace is stripped, empty strings become None, and models starting with `-` are rejected (flag injection prevention).

## Security Notes

**Model validation**: Model parameters are validated to prevent flag injection. Values starting with `-` are rejected at both the server level (`_resolve_model`) and adapter level (`build_command`) as defense-in-depth.

**Codex adapter**: `OPENAI_API_KEY` is passed to spawned Codex processes (required for authentication). This is intentional but means prompts could theoretically exfiltrate the key.

## Release Process

Uses release-please for automated releases. CI publishes to PyPI on release tags. Version is maintained in `src/moonbridge/__init__.py`.
