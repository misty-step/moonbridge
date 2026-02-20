# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Moonbridge

An MCP server that spawns AI coding agents from any MCP client. Supports multiple backends (Kimi, Codex, OpenCode, Gemini) with parallel execution—run 10 approaches simultaneously for a fraction of the cost.

## Commands

```bash
# Development
uv sync                      # Install dependencies
uv sync --extra dev          # Install with dev dependencies

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
├── server.py          # MCP server entrypoint and orchestration helper wiring
├── tool_handlers.py   # MCP protocol-layer dispatch and response serialization
├── sandbox.py         # Copy-on-run sandbox + diff utilities
├── version_check.py   # Update notification (24h cache)
└── adapters/
    ├── base.py        # CLIAdapter protocol and AdapterConfig dataclass
    ├── kimi.py        # Kimi CLI adapter implementation
    ├── codex.py       # Codex CLI adapter implementation
    ├── opencode.py    # OpenCode CLI adapter implementation
    ├── gemini.py      # Gemini CLI adapter implementation
    └── __init__.py    # Adapter registry and get_adapter()
```

**Adapter pattern**: The codebase uses a protocol-based adapter pattern to support multiple CLI backends. `CLIAdapter` defines the interface; each adapter implements `build_command()`, `check_installed()`, and `list_models()`. Kimi, Codex, OpenCode, and Gemini are implemented. Adapters with static model catalogs delegate to `static_model_catalog()` from `base.py`; only OpenCode queries its CLI dynamically. Adapter-specific capabilities (e.g., provider filtering) are declared via `AdapterConfig` flags (`supports_provider_filter`) rather than string comparisons against adapter names.

**Protocol boundary**: `tool_handlers.py` owns MCP protocol dispatch (`spawn_agent`, `spawn_agents_parallel`, status/list calls) and stable response payload shaping. `server.py` provides orchestration callbacks (validation, adapter resolution, process execution).

**Process lifecycle**: Agents spawn as subprocess with `start_new_session=True` for clean process group management. Orphan cleanup is registered via `atexit`. Processes are tracked via weak references in `_active_processes`.

**Environment sandboxing**: Only whitelisted env vars (`safe_env_keys`) are passed to spawned processes. Directory restrictions via `MOONBRIDGE_ALLOWED_DIRS`.

## MCP Tools Exposed

| Tool | Purpose |
|------|---------|
| `spawn_agent` | Single agent execution |
| `spawn_agents_parallel` | Up to 10 agents concurrently |
| `list_adapters` | List available adapters and their status |
| `list_models` | List model options for an adapter |
| `check_status` | Verify CLI installation and auth |

### Tool Parameters

Both `spawn_agent` and `spawn_agents_parallel` support:
- `adapter`: Backend to use (`kimi`, `codex`, `opencode`, `gemini`)
- `model`: Model name (e.g., `gpt-5.2-codex`, `kimi-k2.5`, `openrouter/minimax/minimax-m2.5`, `gemini-2.5-pro`)
- `thinking`: Enable extended reasoning (Kimi only)
- `reasoning_effort`: Reasoning budget for Codex (`low`, `medium`, `high`, `xhigh`)
- `timeout_seconds`: Max execution time (30-3600s)

`check_status` supports optional:
- `adapter`: Which adapter to validate (defaults to `MOONBRIDGE_ADAPTER`)

`list_models` supports optional:
- `adapter`: Which adapter catalog to return
- `provider`: Provider filter (OpenCode only)
- `refresh`: Refresh dynamic catalog (OpenCode)

## Testing

Tests mock `Popen` and `shutil.which` to avoid requiring Kimi CLI. See `conftest.py` for fixtures:
- `mock_popen` - Mock subprocess execution
- `mock_which_kimi` - Mock Kimi CLI found
- `mock_which_no_kimi` - Mock Kimi CLI not found
- `mock_which_codex` / `mock_which_no_codex` - Codex install checks
- `mock_which_opencode` / `mock_which_no_opencode` - OpenCode install checks
- `mock_which_gemini` / `mock_which_no_gemini` - Gemini install checks

The MCP library is also stubbed in conftest when not installed, enabling tests to run without the full MCP dependency.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MOONBRIDGE_ADAPTER` | `kimi` | CLI backend to use (`kimi`, `codex`, `opencode`, `gemini`) |
| `MOONBRIDGE_TIMEOUT` | `600` | Global timeout fallback (30-3600s) |
| `MOONBRIDGE_CODEX_TIMEOUT` | `1800` | Codex-specific timeout (30min default) |
| `MOONBRIDGE_KIMI_TIMEOUT` | `600` | Kimi-specific timeout (10min default) |
| `MOONBRIDGE_OPENCODE_TIMEOUT` | `1200` | OpenCode-specific timeout (20min default) |
| `MOONBRIDGE_GEMINI_TIMEOUT` | `1200` | Gemini-specific timeout (20min default) |
| `MOONBRIDGE_MAX_AGENTS` | `10` | Max parallel agents |
| `MOONBRIDGE_MAX_OUTPUT_CHARS` | `120000` | Max chars returned per agent across `stdout`+`stderr` (timeout tails are per stream) |
| `MOONBRIDGE_MAX_RESPONSE_BYTES` | `5000000` | Max serialized response bytes before circuit breaker |
| `MOONBRIDGE_ALLOWED_DIRS` | (none) | Colon-separated directory allowlist |
| `MOONBRIDGE_STRICT` | `false` | Exit if ALLOWED_DIRS unset |
| `MOONBRIDGE_LOG_LEVEL` | `WARNING` | Logging verbosity |
| `MOONBRIDGE_MODEL` | (none) | Global default model for all adapters |
| `MOONBRIDGE_KIMI_MODEL` | (none) | Kimi-specific model override |
| `MOONBRIDGE_CODEX_MODEL` | (none) | Codex-specific model override (default model: `gpt-5.3-codex`) |
| `MOONBRIDGE_OPENCODE_MODEL` | (none) | OpenCode-specific model override |
| `MOONBRIDGE_GEMINI_MODEL` | (none) | Gemini-specific model override (default model: `gemini-2.5-pro`) |

Timeout resolution order: tool param > adapter env var > adapter default > global env var > 600s.

Model resolution order: tool param > adapter env var > global env var > adapter default > CLI default.

Reasoning effort resolution order: tool param > adapter default (`codex` = `xhigh`).

All model values are validated: whitespace is stripped, empty strings become None, and models starting with `-` are rejected (flag injection prevention).

## Security Notes

**Model validation**: Model parameters are validated to prevent flag injection. Values starting with `-` are rejected at both the server level (`_resolve_model`) and adapter level (`build_command`) as defense-in-depth.

**Adapter auth env vars**: adapter-specific keys are passed when allowlisted (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, etc.). This is intentional for auth, but prompts could theoretically exfiltrate these values.

## Release Process

Uses release-please for automated releases. CI publishes to PyPI on release tags. Version is maintained in `src/moonbridge/__init__.py`.
