from moonbridge.signals import extract_quality_signals


def test_extract_quality_signals_empty_output() -> None:
    assert extract_quality_signals("", None) == {}


def test_extract_quality_signals_pytest_counts() -> None:
    output = "== 5 passed, 2 failed in 0.12s =="
    assert extract_quality_signals(output) == {"tests_passed": 5, "tests_failed": 2}


def test_extract_quality_signals_diff_markers() -> None:
    output = (
        "diff --git a/foo.py b/foo.py\n"
        "index 123..456 100644\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/bar.py b/bar.py\n"
        "--- a/bar.py\n"
        "+++ b/bar.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    assert extract_quality_signals(output) == {"has_diff": True, "files_changed": 2}


def test_extract_quality_signals_traceback() -> None:
    stderr = "Traceback (most recent call last):\n  boom\n"
    assert extract_quality_signals("", stderr) == {"has_errors": True}


def test_extract_quality_signals_combined() -> None:
    output = "2 passed, 1 failed\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n"
    stderr = "error: something went wrong\n"
    assert extract_quality_signals(output, stderr) == {
        "tests_passed": 2,
        "tests_failed": 1,
        "has_diff": True,
        "files_changed": 1,
        "has_errors": True,
    }


def test_extract_quality_signals_zero_passed() -> None:
    """Zero passed should be reported, not silently dropped."""
    output = "== 0 passed, 3 failed in 0.05s =="
    assert extract_quality_signals(output) == {"tests_passed": 0, "tests_failed": 3}


def test_extract_quality_signals_zero_failed() -> None:
    """Zero failed is a meaningful signal (all tests passed)."""
    output = "== 5 passed, 0 failed in 0.12s =="
    assert extract_quality_signals(output) == {"tests_passed": 5, "tests_failed": 0}


def test_extract_quality_signals_files_changed_summary() -> None:
    """Fallback to git summary line when no diff headers present."""
    output = "3 files changed, 10 insertions(+), 2 deletions(-)\n"
    assert extract_quality_signals(output) == {"files_changed": 3}


def test_extract_quality_signals_modified_files_summary() -> None:
    """Fallback to Modified N files format."""
    output = "Modified 2 files\n"
    assert extract_quality_signals(output) == {"files_changed": 2}


def test_extract_quality_signals_last_match_wins() -> None:
    """When output has multiple test runs, the last result is used."""
    output = (
        "== 3 passed in 0.1s ==\n"
        "== 5 passed, 1 failed in 0.2s ==\n"
    )
    assert extract_quality_signals(output) == {"tests_passed": 5, "tests_failed": 1}


def test_extract_quality_signals_no_signals_on_plain_output() -> None:
    output = "All done, no issues found.\n"
    assert extract_quality_signals(output) == {}


def test_extract_quality_signals_real_worldish_codex_output() -> None:
    output = (
        "Running: uv run pytest -v\n"
        "============================= test session starts ==============================\n"
        "collected 7 items\n"
        "tests/test_server.py ....F..\n"
        "=========================== short test summary info ============================\n"
        "FAILED tests/test_server.py::test_spawn_agent - AssertionError\n"
        "========================= 6 passed, 1 failed in 0.45s =========================\n"
        "diff --git a/src/app.py b/src/app.py\n"
        "index 123..456 100644\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
    )
    assert extract_quality_signals(output) == {
        "tests_passed": 6,
        "tests_failed": 1,
        "has_diff": True,
        "files_changed": 1,
    }
