"""Heuristic extraction of quality signals from agent output."""

from __future__ import annotations

import re
from typing import Any

# Diff markers at line start.
_DIFF_MARKER_RE = re.compile(r"^(?:\+\+\+ |--- |@@ )", re.MULTILINE)
# File headers in unified diffs.
_DIFF_FILE_RE = re.compile(r"^(?:\+\+\+ b/|--- a/)(.+)$", re.MULTILINE)
# Git-style summary lines.
_FILES_CHANGED_RE = re.compile(r"\b(\d+)\s+files?\s+changed\b", re.IGNORECASE)
_MODIFIED_FILES_RE = re.compile(r"\bModified\s+(\d+)\s+files?\b", re.IGNORECASE)
# Pytest-style summaries.
_PASSED_RE = re.compile(r"(?<!\w)(\d+)\s+passed\b", re.IGNORECASE)
_FAILED_RE = re.compile(r"(?<!\w)(\d+)\s+failed\b", re.IGNORECASE)
# stderr error markers.
_ERROR_RE = re.compile(r"(Traceback \(most recent call last\)|\berror:)", re.IGNORECASE)


def _last_int(pattern: re.Pattern[str], text: str) -> int | None:
    matches = pattern.findall(text)
    if not matches:
        return None
    return int(matches[-1])


def _count_files_changed(output: str) -> int:
    paths = {path for path in _DIFF_FILE_RE.findall(output) if path and path != "/dev/null"}
    if paths:
        return len(paths)
    match = _FILES_CHANGED_RE.search(output) or _MODIFIED_FILES_RE.search(output)
    if match:
        return int(match.group(1))
    return 0


def extract_quality_signals(output: str, stderr: str | None = None) -> dict[str, Any]:
    """Extract heuristic quality signals from agent output."""
    signals: dict[str, Any] = {}
    if not output and not stderr:
        return signals

    has_diff = bool(_DIFF_MARKER_RE.search(output))
    if has_diff:
        signals["has_diff"] = True

    files_changed = _count_files_changed(output)
    if files_changed:
        signals["files_changed"] = files_changed

    combined = output
    if stderr:
        combined = f"{output}\n{stderr}"

    tests_passed = _last_int(_PASSED_RE, combined)
    if tests_passed:
        signals["tests_passed"] = tests_passed

    tests_failed = _last_int(_FAILED_RE, combined)
    if tests_failed:
        signals["tests_failed"] = tests_failed

    if stderr and _ERROR_RE.search(stderr):
        signals["has_errors"] = True

    return signals
