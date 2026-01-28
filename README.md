# Moonbridge

**Your MCP client just got a team.**

Spawn Kimi K2.5 agents from Claude Code, Cursor, or any MCP client. Run 10 approaches in parallel for the cost of one Claude request.

```bash
uvx moonbridge
```

## Quick Start

1. **Install Kimi CLI and authenticate:**
   ```bash
   uv tool install --python 3.13 kimi-cli && kimi login
   ```

2. **Add to MCP config** (`~/.mcp.json`):
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

3. **Use it.** Your MCP client now has `spawn_agent` and `spawn_agents_parallel` tools.

## Updating

Moonbridge checks for updates on startup (cached for 24h). To update manually:

```bash
# If using uvx (recommended)
uvx moonbridge --refresh

# If installed as a tool
uv tool upgrade moonbridge
```

Disable update checks for CI/automation:

```bash
export MOONBRIDGE_SKIP_UPDATE_CHECK=1
```

## When to Use Moonbridge

| Task | Why Moonbridge |
|------|----------------|
| Parallel exploration | Run 10 approaches simultaneously, pick the best |
| Frontend/UI work | Kimi excels at visual coding and component design |
| Tests and documentation | Cost-effective for high-volume tasks |
| Refactoring | Try multiple strategies in one request |

**Best for:** Tasks that benefit from parallel execution or volume.

## Tools

| Tool | Use case |
|------|----------|
| `spawn_agent` | Single task: "Write tests for auth.ts" |
| `spawn_agents_parallel` | Go wide: 10 agents, 10 approaches, pick the best |
| `check_status` | Verify Kimi CLI is installed and authenticated |

### Example: Parallel Exploration

```json
{
  "agents": [
    {"prompt": "Refactor to React hooks"},
    {"prompt": "Refactor to Zustand"},
    {"prompt": "Refactor to Redux Toolkit"}
  ]
}
```

Three approaches. One request. You choose the winner.

### Tool Parameters

**`spawn_agent`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt` | string | Yes | Task description for the agent |
| `thinking` | boolean | No | Enable reasoning mode (default: false) |
| `timeout_seconds` | integer | No | Override default timeout (30-3600) |

**`spawn_agents_parallel`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agents` | array | Yes | List of agent configs (max 10) |
| `agents[].prompt` | string | Yes | Task for this agent |
| `agents[].thinking` | boolean | No | Enable reasoning for this agent |
| `agents[].timeout_seconds` | integer | No | Timeout for this agent |

## Response Format

All tools return JSON with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `success`, `error`, `timeout`, `auth_error`, or `cancelled` |
| `output` | string | stdout from Kimi agent |
| `stderr` | string\|null | stderr if any |
| `returncode` | int | Process exit code (-1 for timeout/error) |
| `duration_ms` | int | Execution time in milliseconds |
| `agent_index` | int | Agent index (0 for single, 0-N for parallel) |
| `message` | string? | Human-readable error context (when applicable) |

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `MOONBRIDGE_ADAPTER` | Default adapter (default: `kimi`) |
| `MOONBRIDGE_TIMEOUT` | Default timeout in seconds (30-3600) |
| `MOONBRIDGE_MAX_AGENTS` | Maximum parallel agents |
| `MOONBRIDGE_ALLOWED_DIRS` | Colon-separated allowlist of working directories |
| `MOONBRIDGE_STRICT` | Set to `1` to require `ALLOWED_DIRS` (exits if unset) |
| `MOONBRIDGE_LOG_LEVEL` | Set to `DEBUG` for verbose logging |

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

### "MOONBRIDGE_ALLOWED_DIRS is not set" warning

By default, Moonbridge warns at startup if no directory restrictions are configured. This is expected for local development. For shared/production environments, set allowed directories:

```bash
export MOONBRIDGE_ALLOWED_DIRS="/path/to/project:/another/path"
```

To enforce restrictions (exit instead of warn):

```bash
export MOONBRIDGE_STRICT=1
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

## Platform Support

macOS and Linux only. Windows is not supported.

## License

MIT. See `LICENSE`.
