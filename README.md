# Moonbridge

MCP server for spawning Kimi K2.5 agents.

## What it does

Moonbridge lets MCP clients delegate tasks to Kimi K2.5 agents.
Use it for cost-effective parallel execution and strong frontend output.

## Installation

```bash
pip install moonbridge
```

Or run without install:

```bash
uvx moonbridge
```

## Prerequisites

1. Install Kimi CLI:
   ```bash
   uv tool install --python 3.13 kimi-cli
   ```
2. Authenticate:
   ```bash
   kimi login
   ```

## MCP configuration

`~/.mcp.json`:

```json
{
  "mcpServers": {
    "moonbridge": {
      "type": "stdio",
      "command": "uvx",
      "args": ["moonbridge"]
    }
  }
}
```

If installed globally:

```json
{
  "mcpServers": {
    "moonbridge": {
      "type": "stdio",
      "command": "moonbridge"
    }
  }
}
```

## Tools

### spawn_agent

Spawn a single Kimi agent in the current working directory.

```json
{
  "prompt": "Create a React component for user authentication",
  "thinking": false,
  "timeout_seconds": 600
}
```

### spawn_agents_parallel

Spawn multiple agents in parallel.

```json
{
  "agents": [
    {"prompt": "Write unit tests for auth.ts"},
    {"prompt": "Write integration tests for auth flow", "thinking": true}
  ]
}
```

### check_status

Verify Kimi CLI is installed and authenticated.

```json
{}
```

## Environment variables

- `MOONBRIDGE_TIMEOUT`: default timeout seconds (30-3600)
- `MOONBRIDGE_MAX_AGENTS`: max parallel agents
- `MOONBRIDGE_ALLOWED_DIRS`: colon-separated allowlist of working dirs

## Response format

All tools return JSON with these fields:

| Field | Type | Description |
| --- | --- | --- |
| `status` | string | `success`, `error`, `timeout`, `auth_error`, or `cancelled` |
| `output` | string | stdout from Kimi agent |
| `stderr` | string\|null | stderr if any |
| `returncode` | int | Process exit code (-1 for timeout/error) |
| `duration_ms` | int | Execution time in milliseconds |
| `agent_index` | int | Agent index (0 for single, 0-N for parallel) |
| `message` | string? | Human-readable error context (when applicable) |

## Troubleshooting

### "Kimi CLI not found"

Install the Kimi CLI:

```bash
uv tool install --python 3.13 kimi-cli
which kimi
```

### "auth_error" responses

Authenticate with Kimi:

```bash
kimi login
```

### Timeout errors

Increase the timeout for long-running tasks:

```json
{"prompt": "...", "timeout_seconds": 1800}
```

Or set a global default:

```bash
export MOONBRIDGE_TIMEOUT=1800
```

### Permission denied on working directory

Verify the directory is in your allowlist:

```bash
export MOONBRIDGE_ALLOWED_DIRS="/path/to/project:/another/path"
```

### Debug logging

Enable verbose logging:

```bash
export MOONBRIDGE_LOG_LEVEL=DEBUG
```

## Platform support

macOS and Linux only. Windows is not supported.

## When to use Kimi vs Codex

| Task | Recommendation |
| --- | --- |
| Standard implementation | Codex |
| Budget-conscious work | Kimi |
| Frontend/visual coding | Kimi |
| Complex multi-step | Kimi |
| Git-heavy workflows | Codex |

## License

MIT. See `LICENSE`.
