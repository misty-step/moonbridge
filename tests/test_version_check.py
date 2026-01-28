"""Tests for version check functionality."""

import json
import logging
import os
import time
from unittest.mock import patch

import pytest

from moonbridge.version_check import (
    CACHE_TTL_SECONDS,
    MAX_CACHE_SIZE,
    MAX_CLOCK_SKEW,
    NEGATIVE_CACHE_TTL_SECONDS,
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

    def test_partial_versions(self):
        # Two-part versions should work (padded comparison)
        assert _compare_versions("1.0", "1.1") is True
        assert _compare_versions("1.1", "1.0") is False


class TestCheckForUpdates:
    @pytest.fixture(autouse=True)
    def clear_env(self):
        """Ensure env var is cleared for each test."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOONBRIDGE_SKIP_UPDATE_CHECK", None)
            yield

    def test_skip_when_env_set(self, caplog):
        with patch.dict(os.environ, {"MOONBRIDGE_SKIP_UPDATE_CHECK": "1"}):
            check_for_updates("0.2.1")
        assert "available" not in caplog.text

    def test_skip_when_env_true(self, caplog):
        with patch.dict(os.environ, {"MOONBRIDGE_SKIP_UPDATE_CHECK": "true"}):
            check_for_updates("0.2.1")
        assert "available" not in caplog.text

    def test_skip_when_env_yes(self, caplog):
        with patch.dict(os.environ, {"MOONBRIDGE_SKIP_UPDATE_CHECK": "yes"}):
            check_for_updates("0.2.1")
        assert "available" not in caplog.text

    @pytest.mark.parametrize("value", ["TRUE", "True", "YES", "Yes", "  1  ", " true "])
    def test_skip_case_insensitive_and_whitespace(self, value, caplog):
        """Env var should be case-insensitive and strip whitespace."""
        with patch.dict(os.environ, {"MOONBRIDGE_SKIP_UPDATE_CHECK": value}):
            check_for_updates("0.2.1")
        assert "available" not in caplog.text

    @patch("moonbridge.version_check._read_cache")
    @patch("moonbridge.version_check._fetch_latest_version")
    def test_logs_warning_when_update_available(self, mock_fetch, mock_cache, caplog):
        mock_cache.return_value = None
        mock_fetch.return_value = "0.3.0"
        caplog.set_level(logging.WARNING)

        check_for_updates("0.2.1")

        assert "0.3.0 available" in caplog.text
        assert "uvx moonbridge --refresh" in caplog.text

    @patch("moonbridge.version_check._read_cache")
    @patch("moonbridge.version_check._fetch_latest_version")
    def test_no_warning_when_up_to_date(self, mock_fetch, mock_cache, caplog):
        mock_cache.return_value = None
        mock_fetch.return_value = "0.2.1"

        check_for_updates("0.2.1")

        assert "available" not in caplog.text

    @patch("moonbridge.version_check._read_cache")
    @patch("moonbridge.version_check._fetch_latest_version")
    @patch("moonbridge.version_check._write_cache")
    def test_negative_cache_on_network_error(self, mock_write, mock_fetch, mock_cache, caplog):
        """Failed fetch should write negative cache to prevent repeated blocking."""
        mock_cache.return_value = None
        mock_fetch.return_value = None

        check_for_updates("0.2.1")

        # Should write None to cache (negative cache)
        mock_write.assert_called_once_with(None)
        assert "available" not in caplog.text

    @patch("moonbridge.version_check._read_cache")
    @patch("moonbridge.version_check._fetch_latest_version")
    def test_negative_cache_skips_fetch(self, mock_fetch, mock_cache, caplog):
        """Negative cache hit should skip network fetch."""
        # Cache without latest_version = negative cache
        mock_cache.return_value = {"timestamp": time.time()}

        check_for_updates("0.2.1")

        mock_fetch.assert_not_called()
        assert "available" not in caplog.text

    @patch("moonbridge.version_check._read_cache")
    def test_uses_cache_when_valid(self, mock_cache, caplog):
        mock_cache.return_value = {"latest_version": "0.3.0", "timestamp": time.time()}
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

    def test_write_negative_cache(self, tmp_path, monkeypatch):
        """Writing None should create negative cache (no latest_version key)."""
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        _write_cache(None)
        result = _read_cache()

        assert result is not None
        assert "latest_version" not in result
        assert "timestamp" in result

    def test_cache_expired(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        cache_file.write_text(
            json.dumps(
                {
                    "latest_version": "1.0.0",
                    "timestamp": time.time() - CACHE_TTL_SECONDS - 1,
                }
            )
        )

        result = _read_cache()
        assert result is None

    def test_negative_cache_shorter_ttl(self, tmp_path, monkeypatch):
        """Negative cache should expire after 1 hour, not 24 hours."""
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        # Negative cache 2 hours old - should be expired
        cache_file.write_text(
            json.dumps({"timestamp": time.time() - NEGATIVE_CACHE_TTL_SECONDS - 1})
        )

        result = _read_cache()
        assert result is None

    def test_negative_cache_still_valid(self, tmp_path, monkeypatch):
        """Negative cache should be valid within 1 hour."""
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        # Negative cache 30 minutes old - should still be valid
        cache_file.write_text(
            json.dumps({"timestamp": time.time() - (30 * 60)})
        )

        result = _read_cache()
        assert result is not None

    def test_oversized_cache_rejected(self, tmp_path, monkeypatch):
        """Cache files larger than MAX_CACHE_SIZE should be rejected."""
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        # Write oversized cache
        cache_file.write_text("x" * (MAX_CACHE_SIZE + 1))

        result = _read_cache()
        assert result is None

    def test_future_timestamp_rejected(self, tmp_path, monkeypatch):
        """Cache with future timestamp beyond skew tolerance should be rejected."""
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        cache_file.write_text(
            json.dumps(
                {
                    "latest_version": "1.0.0",
                    "timestamp": time.time() + MAX_CLOCK_SKEW + 100,
                }
            )
        )

        result = _read_cache()
        assert result is None

    def test_small_future_timestamp_allowed(self, tmp_path, monkeypatch):
        """Cache with small future timestamp (within skew) should be allowed."""
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        cache_file.write_text(
            json.dumps(
                {
                    "latest_version": "1.0.0",
                    "timestamp": time.time() + 30,  # 30 seconds in future, within skew
                }
            )
        )

        result = _read_cache()
        assert result is not None

    def test_invalid_json_rejected(self, tmp_path, monkeypatch):
        """Corrupted cache file should be silently rejected."""
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        cache_file.write_text("not valid json {{{")

        result = _read_cache()
        assert result is None

    def test_wrong_timestamp_type_rejected(self, tmp_path, monkeypatch):
        """Cache with non-numeric timestamp should be rejected."""
        cache_file = tmp_path / "version_check.json"
        monkeypatch.setattr("moonbridge.version_check.CACHE_FILE", cache_file)

        cache_file.write_text(json.dumps({"latest_version": "1.0.0", "timestamp": "not-a-number"}))

        result = _read_cache()
        assert result is None
