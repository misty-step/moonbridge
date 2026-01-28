# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.2.0...moonbridge-v0.2.1) (2026-01-28)


### Bug Fixes

* **ci:** chain publish job in release-please workflow ([d7295cc](https://github.com/misty-step/moonbridge/commit/d7295cce2f74c77abf6321ab2906e6b46e9af21d))

## [0.2.0](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.1.0...moonbridge-v0.2.0) (2026-01-28)


### Features

* initial moonbridge MCP server ([3debd32](https://github.com/misty-step/moonbridge/commit/3debd325a1619bbbfe980a258c134665bce36e6d))

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
