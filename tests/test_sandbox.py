import importlib
from pathlib import Path
from typing import Any

import pytest

from moonbridge.adapters.base import AgentResult

sandbox_module = importlib.import_module("moonbridge.sandbox")


def _success_result(agent_index: int = 0) -> AgentResult:
    return AgentResult(
        status="success",
        output="ok",
        stderr=None,
        returncode=0,
        duration_ms=1,
        agent_index=agent_index,
    )


def test_diff_trees_no_changes(tmp_path: Path) -> None:
    original = tmp_path / "original"
    sandbox = tmp_path / "sandbox"
    original.mkdir()
    sandbox.mkdir()
    (original / "a.txt").write_text("same", encoding="utf-8")
    (sandbox / "a.txt").write_text("same", encoding="utf-8")

    diff, summary, truncated = sandbox_module._diff_trees(
        str(original), str(sandbox), 500_000
    )

    assert diff == ""
    assert summary == {"added": 0, "modified": 0, "deleted": 0, "binary": 0}
    assert truncated is False


def test_diff_trees_truncation(tmp_path: Path) -> None:
    original = tmp_path / "original"
    sandbox = tmp_path / "sandbox"
    original.mkdir()
    sandbox.mkdir()
    (sandbox / "big.txt").write_text("x" * 1000, encoding="utf-8")

    diff, summary, truncated = sandbox_module._diff_trees(str(original), str(sandbox), 50)

    assert truncated is True
    assert "... diff truncated ..." in diff
    assert summary["added"] == 1


def test_diff_trees_binary_file(tmp_path: Path) -> None:
    original = tmp_path / "original"
    sandbox = tmp_path / "sandbox"
    original.mkdir()
    sandbox.mkdir()
    (sandbox / "img.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x80\xff")

    diff, summary, truncated = sandbox_module._diff_trees(
        str(original), str(sandbox), 500_000
    )

    assert summary["added"] == 1
    assert summary["binary"] == 1
    assert "Binary files" in diff
    assert truncated is False


def test_run_sandboxed_keep_preserves_dir(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "keep.txt").write_text("keep", encoding="utf-8")

    sandbox_root = tmp_path / "sandbox"

    def fake_mkdtemp(*_args: Any, **_kwargs: Any) -> str:
        sandbox_root.mkdir()
        return str(sandbox_root)

    monkeypatch.setattr(sandbox_module.tempfile, "mkdtemp", fake_mkdtemp)

    result, sandbox_result = sandbox_module.run_sandboxed(
        lambda _cwd: _success_result(),
        str(workspace),
        keep=True,
    )

    assert result.status == "success"
    assert sandbox_result is not None
    assert sandbox_result.sandbox_path == str(sandbox_root)
    assert sandbox_root.exists()


def test_run_sandboxed_cleanup_on_success(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "keep.txt").write_text("keep", encoding="utf-8")

    sandbox_root = tmp_path / "sandbox"

    def fake_mkdtemp(*_args: Any, **_kwargs: Any) -> str:
        sandbox_root.mkdir()
        return str(sandbox_root)

    monkeypatch.setattr(sandbox_module.tempfile, "mkdtemp", fake_mkdtemp)

    result, sandbox_result = sandbox_module.run_sandboxed(
        lambda _cwd: _success_result(),
        str(workspace),
        keep=False,
    )

    assert result.status == "success"
    assert sandbox_result is not None
    assert not sandbox_root.exists()


def test_run_sandboxed_cleanup_on_error(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "keep.txt").write_text("keep", encoding="utf-8")

    sandbox_root = tmp_path / "sandbox"

    def fake_mkdtemp(*_args: Any, **_kwargs: Any) -> str:
        sandbox_root.mkdir()
        return str(sandbox_root)

    monkeypatch.setattr(sandbox_module.tempfile, "mkdtemp", fake_mkdtemp)

    def boom(_cwd: str) -> AgentResult:
        raise RuntimeError("boom")

    result, sandbox_result = sandbox_module.run_sandboxed(boom, str(workspace))

    assert result.status == "error"
    assert sandbox_result is None
    assert not sandbox_root.exists()


def test_diff_failure_returns_error_in_sandbox(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "keep.txt").write_text("keep", encoding="utf-8")

    def raise_diff(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(sandbox_module, "_diff_trees", raise_diff)

    result, sandbox_result = sandbox_module.run_sandboxed(
        lambda _cwd: _success_result(),
        str(workspace),
    )

    assert result.status == "success"
    assert sandbox_result is None
    assert result.raw is not None
    assert "sandbox" in result.raw
    assert "error" in result.raw["sandbox"]


def test_max_copy_size_exceeded(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "big.txt").write_bytes(b"x" * 20)

    def no_copy(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("copy should not start")

    monkeypatch.setattr(sandbox_module.tempfile, "mkdtemp", no_copy)

    def should_not_run(_cwd: str) -> AgentResult:
        raise AssertionError("agent should not run")

    result, sandbox_result = sandbox_module.run_sandboxed(
        should_not_run,
        str(workspace),
        max_copy_bytes=10,
    )

    assert result.status == "error"
    assert result.stderr
    assert "exceeds max" in result.stderr
    assert sandbox_result is None


def test_ignore_patterns_unified(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".DS_Store").write_text("ignored", encoding="utf-8")

    def run_agent(sandbox_cwd: str) -> AgentResult:
        sandbox_path = Path(sandbox_cwd)
        assert not sandbox_path.joinpath(".DS_Store").exists()
        sandbox_path.joinpath(".DS_Store").write_text("new", encoding="utf-8")
        return _success_result()

    result, sandbox_result = sandbox_module.run_sandboxed(run_agent, str(workspace))

    assert result.status == "success"
    assert sandbox_result is not None
    assert sandbox_result.diff == ""
    assert sandbox_result.summary == {"added": 0, "modified": 0, "deleted": 0, "binary": 0}
