# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.5.2...moonbridge-v0.6.0) (2026-02-03)


### Features

* add AgentResult dataclass for typed result handling ([#63](https://github.com/misty-step/moonbridge/issues/63)) ([75e369f](https://github.com/misty-step/moonbridge/commit/75e369f5c00dece7d770c2a4a0b0cb804c422f81))

## [0.5.2](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.5.1...moonbridge-v0.5.2) (2026-02-01)


### Bug Fixes

* handle ProcessLookupError on SIGKILL path in _terminate_process ([#58](https://github.com/misty-step/moonbridge/issues/58)) ([b52d745](https://github.com/misty-step/moonbridge/commit/b52d7452bdc1777d63c42a2ce70d6e290f9b0c54))

## [0.5.1](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.5.0...moonbridge-v0.5.1) (2026-02-01)


### Bug Fixes

* **ci:** trigger publish.yml instead of duplicating PyPI publish ([#56](https://github.com/misty-step/moonbridge/issues/56)) ([fb4aa6b](https://github.com/misty-step/moonbridge/commit/fb4aa6b6a8ece7047dcc105179780c0750da1160))

## [0.5.0](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.4.1...moonbridge-v0.5.0) (2026-01-31)


### Features

* add Codex CLI as second backend adapter ([#54](https://github.com/misty-step/moonbridge/issues/54)) ([966d600](https://github.com/misty-step/moonbridge/commit/966d6005162a1ea3bbb51aa7fd145be4a2e337a4))

## [0.4.1](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.4.0...moonbridge-v0.4.1) (2026-01-28)


### Bug Fixes

* **security:** warn when ALLOWED_DIRS is empty ([#46](https://github.com/misty-step/moonbridge/issues/46)) ([d9a9e0f](https://github.com/misty-step/moonbridge/commit/d9a9e0f65d3e0b556546ae277d4f517c5119dbd1))

## [0.4.0](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.3.0...moonbridge-v0.4.0) (2026-01-28)


### Features

* add startup version check to notify users of updates ([#43](https://github.com/misty-step/moonbridge/issues/43)) ([32c09ee](https://github.com/misty-step/moonbridge/commit/32c09ee1325267f73504c56cdc1b7af73ce60fa7))

## [0.3.0](https://github.com/misty-step/moonbridge/compare/moonbridge-v0.2.1...moonbridge-v0.3.0) (2026-01-28)


### Features

* **adapters:** configurable default adapter via MOONBRIDGE_ADAPTER env var ([#40](https://github.com/misty-step/moonbridge/issues/40)) ([1553dcf](https://github.com/misty-step/moonbridge/commit/1553dcf9ea30c4643b98e054a4fccf473cd68cb9)), closes [#39](https://github.com/misty-step/moonbridge/issues/39)

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
