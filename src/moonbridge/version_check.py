"""Background version check against PyPI."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

logger = logging.getLogger("moonbridge")

PYPI_URL = "https://pypi.org/pypi/moonbridge/json"
CACHE_FILE = Path.home() / ".cache" / "moonbridge" / "version_check.json"
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours
REQUEST_TIMEOUT = 5  # seconds


def _read_cache() -> dict[str, object] | None:
    """Read cached version check result if valid."""
    try:
        if not CACHE_FILE.exists():
            return None
        data: dict[str, object] = json.loads(CACHE_FILE.read_text())
        timestamp = data.get("timestamp", 0)
        if isinstance(timestamp, (int, float)) and time.time() - timestamp < CACHE_TTL_SECONDS:
            return data
    except Exception:
        pass
    return None


def _write_cache(latest_version: str) -> None:
    """Cache version check result."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(
                {
                    "latest_version": latest_version,
                    "timestamp": time.time(),
                }
            )
        )
    except Exception:
        pass  # Silent fail


def _fetch_latest_version() -> str | None:
    """Fetch latest version from PyPI. Returns None on any error."""
    try:
        req = Request(PYPI_URL, headers={"Accept": "application/json"})
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data: dict[str, object] = json.loads(resp.read().decode())
            info = data.get("info")
            if isinstance(info, dict):
                version = info.get("version")
                if isinstance(version, str):
                    return version
            return None
    except Exception:
        return None


def _compare_versions(current: str, latest: str) -> bool:
    """Return True if latest > current (simple tuple comparison)."""
    try:
        def parse(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in v.split(".")[:3])

        return parse(latest) > parse(current)
    except Exception:
        return False


def check_for_updates(current_version: str) -> None:
    """Check PyPI for updates, log warning if newer version available.

    - Skipped if MOONBRIDGE_SKIP_UPDATE_CHECK=1
    - Uses 24h cache to avoid hammering PyPI
    - All errors are silent
    """
    if os.environ.get("MOONBRIDGE_SKIP_UPDATE_CHECK", "").strip() in ("1", "true", "yes"):
        return

    try:
        latest: str | None = None
        cache = _read_cache()
        if cache:
            cached_version = cache.get("latest_version")
            if isinstance(cached_version, str):
                latest = cached_version
        else:
            latest = _fetch_latest_version()
            if latest:
                _write_cache(latest)

        if latest and _compare_versions(current_version, latest):
            logger.warning(
                "Moonbridge %s available (you have %s). "
                "Update: uvx moonbridge --refresh",
                latest,
                current_version,
            )
    except Exception:
        pass  # Silent fail - never break the server
