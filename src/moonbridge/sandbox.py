"""Copy-on-run sandbox for agent execution."""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path

from moonbridge.adapters.base import AgentResult

SANDBOX_IGNORE_DIRS = {
    ".git",
    ".venv",
    ".tox",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}
SANDBOX_IGNORE_FILES = {".DS_Store"}
MAX_COPY_BYTES = 500 * 1024 * 1024


@dataclass(frozen=True)
class SandboxResult:
    diff: str
    summary: dict[str, int]
    truncated: bool
    sandbox_path: str | None


def _should_ignore(name: str) -> bool:
    if name in SANDBOX_IGNORE_DIRS:
        return True
    if name in SANDBOX_IGNORE_FILES:
        return True
    return name.endswith((".pyc", ".pyo"))


def _ignore_names(_dirpath: str, names: list[str]) -> set[str]:
    return {name for name in names if _should_ignore(name)}


def _filtered_walk(root: str) -> Iterator[tuple[str, list[str], list[str]]]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_ignore(d)]
        filenames = [f for f in filenames if not _should_ignore(f)]
        yield dirpath, dirnames, filenames


def _collect_files(root: str) -> set[str]:
    files: set[str] = set()
    for dirpath, _dirnames, filenames in _filtered_walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        for filename in filenames:
            rel_path = filename if rel_dir == "." else os.path.join(rel_dir, filename)
            files.add(rel_path)
    return files


def _read_text(path: str) -> str | None:
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _diff_trees(
    original: str,
    sandbox: str,
    max_bytes: int,
) -> tuple[str, dict[str, int], bool]:
    original_files = _collect_files(original)
    sandbox_files = _collect_files(sandbox)
    all_files = sorted(original_files | sandbox_files)
    diff_chunks: list[str] = []
    size = 0
    truncated = False
    summary = {"added": 0, "modified": 0, "deleted": 0, "binary": 0}

    def append_chunk(chunk: str) -> None:
        nonlocal size, truncated
        if truncated or not chunk:
            return
        remaining = max_bytes - size
        if remaining <= 0:
            truncated = True
            return
        if len(chunk) > remaining:
            diff_chunks.append(chunk[:remaining])
            truncated = True
            size = max_bytes
            return
        diff_chunks.append(chunk)
        size += len(chunk)

    for rel_path in all_files:
        original_path = os.path.join(original, rel_path)
        sandbox_path = os.path.join(sandbox, rel_path)
        original_exists = os.path.exists(original_path)
        sandbox_exists = os.path.exists(sandbox_path)

        if not original_exists and sandbox_exists:
            summary["added"] += 1
            sandbox_text = _read_text(sandbox_path)
            if sandbox_text is None:
                summary["binary"] += 1
                append_chunk(f"Binary files /dev/null and b/{rel_path} differ\n")
                continue
            diff = difflib.unified_diff(
                [],
                sandbox_text.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=f"b/{rel_path}",
            )
            append_chunk("".join(diff))
            continue

        if original_exists and not sandbox_exists:
            summary["deleted"] += 1
            original_text = _read_text(original_path)
            if original_text is None:
                summary["binary"] += 1
                append_chunk(f"Binary files a/{rel_path} and /dev/null differ\n")
                continue
            diff = difflib.unified_diff(
                original_text.splitlines(keepends=True),
                [],
                fromfile=f"a/{rel_path}",
                tofile="/dev/null",
            )
            append_chunk("".join(diff))
            continue

        if not original_exists or not sandbox_exists:
            continue

        original_bytes = Path(original_path).read_bytes()
        sandbox_bytes = Path(sandbox_path).read_bytes()
        if original_bytes == sandbox_bytes:
            continue

        original_text = None
        sandbox_text = None
        try:
            original_text = original_bytes.decode("utf-8")
            sandbox_text = sandbox_bytes.decode("utf-8")
        except UnicodeDecodeError:
            summary["binary"] += 1
            append_chunk(f"Binary files a/{rel_path} and b/{rel_path} differ\n")
            continue

        summary["modified"] += 1
        diff = difflib.unified_diff(
            original_text.splitlines(keepends=True),
            sandbox_text.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
        append_chunk("".join(diff))

    if truncated:
        diff_chunks.append("\n... diff truncated ...\n")
    return ("".join(diff_chunks), summary, truncated)


def _estimate_copy_size(root: str, max_bytes: int) -> int:
    total = 0
    for dirpath, _dirnames, filenames in _filtered_walk(root):
        for filename in filenames:
            path = os.path.join(dirpath, filename)
            total += os.path.getsize(path)
            if total > max_bytes:
                return total
    return total


def _agent_index(fn: Callable[[str], AgentResult]) -> int:
    value = getattr(fn, "agent_index", 0)
    return value if isinstance(value, int) else 0


def run_sandboxed(
    fn: Callable[[str], AgentResult],
    cwd: str,
    *,
    max_diff_bytes: int = 500_000,
    max_copy_bytes: int = MAX_COPY_BYTES,
    keep: bool = False,
) -> tuple[AgentResult, SandboxResult | None]:
    """Run fn in a copy of cwd. Returns (agent_result, sandbox_result).

    On sandbox infrastructure error, returns (error_result, None).
    """
    start = time.monotonic()
    sandbox_root: str | None = None
    agent_index = _agent_index(fn)

    def error_result(reason: str) -> AgentResult:
        duration_ms = int((time.monotonic() - start) * 1000)
        return AgentResult(
            status="error",
            output="",
            stderr=f"sandbox error: {reason}",
            returncode=-1,
            duration_ms=duration_ms,
            agent_index=agent_index,
        )

    try:
        total_bytes = _estimate_copy_size(cwd, max_copy_bytes)
        if total_bytes > max_copy_bytes:
            return error_result(
                f"copy size {total_bytes} exceeds max {max_copy_bytes}"
            ), None

        sandbox_root = tempfile.mkdtemp(prefix="moonbridge-sandbox-")
        sandbox_cwd = os.path.join(sandbox_root, "workspace")
        shutil.copytree(cwd, sandbox_cwd, symlinks=False, ignore=_ignore_names)

        result = fn(sandbox_cwd)

        try:
            diff, summary, truncated = _diff_trees(cwd, sandbox_cwd, max_diff_bytes)
            sandbox_result = SandboxResult(
                diff=diff,
                summary=summary,
                truncated=truncated,
                sandbox_path=sandbox_root if keep else None,
            )
            return result, sandbox_result
        except Exception as exc:
            raw = dict(result.raw or {})
            sandbox_payload: dict[str, object] = {"enabled": True, "error": str(exc)}
            if keep:
                sandbox_payload["path"] = sandbox_root
            raw["sandbox"] = sandbox_payload
            return replace(result, raw=raw), None
    except Exception as exc:
        return error_result(str(exc)), None
    finally:
        if not keep and sandbox_root:
            shutil.rmtree(sandbox_root, ignore_errors=True)
