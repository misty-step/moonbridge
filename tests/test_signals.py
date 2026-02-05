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
