# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-01-28

### Added
- Initial release
- `spawn_agent` tool for single Kimi agent execution
- `spawn_agents_parallel` tool for concurrent agent swarms (up to 10)
- `check_status` tool for CLI verification
- Configurable timeouts (30-3600 seconds)
- Working directory allowlist via `MOONBRIDGE_ALLOWED_DIRS`
- Structured JSON responses with status, output, stderr, and timing
- Authentication error detection with actionable messages
- Process group management for clean termination
- Extended reasoning mode via `thinking` parameter

### Security
- Sanitized environment variables passed to subprocesses
- Symlink-aware path validation to prevent directory traversal
- Prompt length validation to prevent resource exhaustion
