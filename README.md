# Moonbridge

**Your MCP client just got a team.**

Spawn AI coding agents from Claude Code, Cursor, or any MCP client. Run 10 approaches in parallel for a fraction of the cost.

```bash
uvx moonbridge
```

## Quick Start

1. **Install at least one supported CLI:**

   | Adapter | Install | Authenticate |
   |---------|---------|--------------|
   | Kimi (default) | `uv tool install --python 3.13 kimi-cli` | `kimi login` |
   | Codex | `npm install -g @openai/codex` | Set `OPENAI_API_KEY` |

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
| Frontend/UI work | Kimi excels at visual coding; Codex at refactoring |
| Tests and documentation | Cost-effective for high-volume tasks |
| Refactoring | Try multiple strategies in one request |

**Best for:** Tasks that benefit from parallel execution or volume.

## Tools

| Tool | Use case |
|------|----------|
| `spawn_agent` | Single task: "Write tests for auth.ts" |
| `spawn_agents_parallel` | Go wide: 10 agents, 10 approaches, pick the best |
| `check_status` | Verify the configured CLI is installed and authenticated |
| `list_adapters` | Show available adapters and their status |

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
| `adapter` | string | No | Backend to use: `kimi`, `codex` (default: `kimi`) |
| `model` | string | No | Model override (e.g., `gpt-5.2-codex`) |
| `thinking` | boolean | No | Enable reasoning mode (Kimi only) |
| `reasoning_effort` | string | No | Reasoning budget: `low`, `medium`, `high`, `xhigh` (Codex only) |
| `timeout_seconds` | integer | No | Override default timeout (30-3600) |

**`spawn_agents_parallel`**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `agents` | array | Yes | List of agent configs (max 10) |
| `agents[].prompt` | string | Yes | Task for this agent |
| `agents[].adapter` | string | No | Backend for this agent |
| `agents[].model` | string | No | Model override for this agent |
| `agents[].thinking` | boolean | No | Enable reasoning (Kimi only) |
| `agents[].reasoning_effort` | string | No | Reasoning budget (Codex only) |
| `agents[].timeout_seconds` | integer | No | Timeout for this agent |

## Response Format

All tools return JSON with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `success`, `error`, `timeout`, `auth_error`, or `cancelled` |
| `output` | string | stdout from the agent |
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

### "CLI not found"

Install the CLI for your chosen adapter:

```bash
# Kimi
uv tool install --python 3.13 kimi-cli
which kimi

# Codex
npm install -g @openai/codex
which codex
```

### "auth_error" responses

Authenticate with your chosen CLI:

```bash
# Kimi
kimi login

# Codex
export OPENAI_API_KEY=sk-...
```

### Timeout errors

Adapters have sensible defaults: Codex=1800s (30min), Kimi=600s (10min).

For exceptionally long tasks, override explicitly:

```json
{"prompt": "...", "timeout_seconds": 3600}
```

Or set per-adapter defaults via environment:

```bash
export MOONBRIDGE_CODEX_TIMEOUT=2400  # 40 minutes
export MOONBRIDGE_KIMI_TIMEOUT=900    # 15 minutes
```

## Timeout Best Practices

| Task Type | Recommended |
|-----------|-------------|
| Quick query, status | 60-180s |
| Simple edits | 300-600s |
| Feature implementation | 1200-1800s |
| Large refactor | 1800-3600s |

Priority resolution: explicit param > adapter env > adapter default > global env > 600s fallback

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
