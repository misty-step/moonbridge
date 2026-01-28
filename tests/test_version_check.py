"""Tests for version check functionality."""

import json
import os
import time
from unittest.mock import patch

from moonbridge.version_check import (
    _compare_versions,
    _read_cache,
    _write_cache,
    check_for_updates,
)


class TestCompareVersions:
    def test_newer_version(self):
        assert _compare_versions("0.2.1", "0.3.0") is True
        assert _compare_versions("0.2.1", "0.2.2") is True
        assert _compare_versions("0.2.1", "1.0.0") is True

    def test_same_version(self):
        assert _compare_versions("0.2.1", "0.2.1") is False

    def test_older_version(self):
        assert _compare_versions("0.3.0", "0.2.1") is False

    def test_invalid_version(self):
        assert _compare_versions("0.2.1", "invalid") is False
        assert _compare_versions("invalid", "0.2.1") is False


class TestCheckForUpdates:
    def test_skip_when_env_set(self, caplog):
        with patch.dict(os.environ, {"MOONBRIDGE_SKIP_UPDATE_CHECK": "1"}):
            check_for_updates("0.2.1")
        assert "available" not in caplog.text

    def test_skip_when_env_true(self, caplog):
        with patch.dict(os.environ, {"MOONBRIDGE_SKIP_UPDATE_CHECK": "true"}):
            check_for_updates("0.2.1")
        assert "available" not in caplog.text

    @patch("moonbridge.version_check._read_cache")
    @patch("moonbridge.version_check._fetch_latest_version")
    def test_logs_warning_when_update_available(self, mock_fetch, mock_cache, caplog):
        mock_cache.return_value = None
        mock_fetch.return_value = "0.3.0"

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOONBRIDGE_SKIP_UPDATE_CHECK", None)
            import logging

            caplog.set_level(logging.WARNING)
            check_for_updates("0.2.1")

        assert "0.3.0 available" in caplog.text
        assert "uvx moonbridge --refresh" in caplog.text

    @patch("moonbridge.version_check._read_cache")
    @patch("moonbridge.version_check._fetch_latest_version")
    def test_no_warning_when_up_to_date(self, mock_fetch, mock_cache, caplog):
        mock_cache.return_value = None
        mock_fetch.return_value = "0.2.1"

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOONBRIDGE_SKIP_UPDATE_CHECK", None)
            check_for_updates("0.2.1")

        assert "available" not in caplog.text

    @patch("moonbridge.version_check._read_cache")
    @patch("moonbridge.version_check._fetch_latest_version")
    def test_silent_on_network_error(self, mock_fetch, mock_cache, caplog):
        mock_cache.return_value = None
        mock_fetch.return_value = None

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOONBRIDGE_SKIP_UPDATE_CHECK", None)
            check_for_updates("0.2.1")

        assert "available" not in caplog.text

    @patch("moonbridge.version_check._read_cache")
    def test_uses_cache_when_valid(self, mock_cache, caplog):
        mock_cache.return_value = {"latest_version": "0.3.0", "timestamp": time.time()}

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOONBRIDGE_SKIP_UPDATE_CHECK", None)
            import logging

            caplog.set_level(logging.WARNING)
            check_for_updates("0.2.1")

        assert "0.3.0 available" in caplog.text


class TestCache:
    def test_write_and_read_cache(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        _write_cache("1.0.0")
        result = _read_cache()

        assert result is not None
        assert result["latest_version"] == "1.0.0"

    def test_cache_expired(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        cache_file.write_text(
            json.dumps(
                {
                    "latest_version": "1.0.0",
                    "timestamp": time.time() - (25 * 60 * 60),
                }
            )
        )

        result = _read_cache()
        assert result is None
