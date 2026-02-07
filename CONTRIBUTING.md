# Contributing

## Development Setup
- Python 3.11+
- Dependency manager: `uv`
- Install: `uv sync --dev`
- Build backend: hatchling (see `pyproject.toml`)

## Running Tests
- All tests: `pytest -v`
- Single file: `pytest tests/test_server.py -v`
- Single test: `pytest tests/test_server.py::test_spawn_agent -v`
- Tests mock `subprocess` and `shutil`; no real CLI needed

## Code Quality
- Lint: `ruff check src/` (rules: E, F, I, UP, B, SIM)
- Types: `mypy src/` (strict mode)
- Line length: 100
- Target Python: 3.11

## Commit Conventions
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `test:`
- Scope optional: `fix(ci):`, `feat(adapter):`
- Issue refs: `(#N)` suffix
- Examples:
  - `feat: add copy-on-run sandbox mode for agent execution (#70)`
  - `fix: handle ProcessLookupError on SIGKILL path (#58)`
  - `refactor: extract tool schemas to dedicated module (#60)`

## Pull Requests
- Branch from `master`
- CI runs on Python 3.11, 3.12, 3.13
- CI runs `ruff`, `mypy`, `pytest`
- Releases handled by release-please

## Architecture Overview
Moonbridge uses a protocol-based adapter pattern via `CLIAdapter` in `adapters/base.py`.
Each adapter implements `build_command()` and `check_installed()` for consistent CLI calls.
The MCP server lives in `server.py` and owns protocol handling plus process lifecycle.
Deeper architecture notes live in `CLAUDE.md`.
