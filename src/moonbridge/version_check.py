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
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours for successful checks
NEGATIVE_CACHE_TTL_SECONDS = 60 * 60  # 1 hour for failed checks (offline mode)
REQUEST_TIMEOUT = 5  # seconds
MAX_CACHE_SIZE = 10_000  # bytes - cache should be tiny
MAX_RESPONSE_SIZE = 100_000  # bytes - PyPI JSON is ~10KB
MAX_CLOCK_SKEW = 60  # seconds - reject future timestamps beyond this


def _read_cache() -> dict[str, object] | None:
    """Read cached version check result if valid."""
    try:
        if not CACHE_FILE.exists():
            return None
        # Reject oversized cache files (corruption/attack)
        if CACHE_FILE.stat().st_size > MAX_CACHE_SIZE:
            return None
        data: dict[str, object] = json.loads(CACHE_FILE.read_text())
        timestamp = data.get("timestamp", 0)
        if not isinstance(timestamp, (int, float)):
            return None
        now = time.time()
        # Reject future timestamps (clock skew or poisoned cache)
        if timestamp > now + MAX_CLOCK_SKEW:
            return None
        # Use appropriate TTL based on whether we have a version
        ttl = CACHE_TTL_SECONDS if data.get("latest_version") else NEGATIVE_CACHE_TTL_SECONDS
        if now - timestamp < ttl:
            return data
    except Exception:
        pass
    return None


def _write_cache(latest_version: str | None) -> None:
    """Cache version check result. Pass None for negative cache (fetch failed)."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {"timestamp": time.time()}
        if latest_version is not None:
            payload["latest_version"] = latest_version
        CACHE_FILE.write_text(json.dumps(payload))
    except Exception:
        pass  # Silent fail


def _fetch_latest_version() -> str | None:
    """Fetch latest version from PyPI. Returns None on any error."""
    try:
        req = Request(PYPI_URL, headers={"Accept": "application/json"})
        with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            # Limit response size to prevent memory exhaustion
            raw = resp.read(MAX_RESPONSE_SIZE)
            data: dict[str, object] = json.loads(raw.decode())
            info = data.get("info")
            if isinstance(info, dict):
                version = info.get("version")
                if isinstance(version, str) and len(version) <= 50:
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

    - Skipped if MOONBRIDGE_SKIP_UPDATE_CHECK=1/true/yes (case-insensitive)
    - Uses 24h cache for successful checks, 1h for failures (offline mode)
    - All errors are silent
    """
    skip = os.environ.get("MOONBRIDGE_SKIP_UPDATE_CHECK", "").strip().lower()
    if skip in ("1", "true", "yes"):
        return

    try:
        latest: str | None = None
        cache = _read_cache()
        if cache is not None:
            # Cache hit - use cached value (may be None for negative cache)
            cached_version = cache.get("latest_version")
            if isinstance(cached_version, str):
                latest = cached_version
            # If cached_version is None/missing, it's a negative cache - skip fetch
        else:
            # Cache miss - fetch from PyPI
            latest = _fetch_latest_version()
            # Cache result (including None for negative cache)
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
