"""
marketaux.py — Marketaux Live News Provider & Persistent Disk Cache.

Features:
  - Fetches Indian market news from Marketaux REST API.
  - Persists cache to disk across server restarts/reloads (up to 200 items).
  - Rotates page parameter across refreshes, dedupes by uuid, and sorts by published time.
  - Supports configurable interval (default 30 min) and server-side cooldown on manual refresh.
  - Graceful handling of HTTP 402 (stops until next UTC day) and HTTP 429 (60s retry once).
  - Strict audit logging of timestamps, HTTP status, and new UUIDs added.
  - Never fabricates articles and never presents cached items as live.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("market_impact.marketaux")

MARKETAUX_BASE_URL = "https://api.marketaux.com/v1/news/all"
REFRESH_INTERVAL_SECONDS = int(os.getenv("MARKETAUX_REFRESH_INTERVAL", "1800"))  # Default 30 min
MIN_MANUAL_COOLDOWN_SECONDS = 30  # Server-side cooldown for manual refresh
MAX_CACHE_ITEMS = 200

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_FILE = CACHE_DIR / "marketaux_news.json"

_current_page = 1
_lock = threading.Lock()

# In-memory storage: uuid -> article dict
_ARTICLE_CACHE: dict[str, dict[str, Any]] = {}
_LAST_FETCH_TIME: Optional[float] = None
_CACHE_STATUS: str = "not_configured"  # not_configured | ok | rate_limited | daily_quota_reached | error
_DAILY_QUOTA_DATE: Optional[str] = None  # YYYY-MM-DD of UTC quota lockout


def _mask_key(key: str) -> str:
    if not key:
        return "None"
    if len(key) <= 8:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


class MarketauxKeyPool:
    """
    Thread-safe Marketaux API key pool supporting multiple keys, per-key daily quota tracking,
    and automatic failover when 401, 402, or 429 occurs.
    Reads from MARKETAUX_API_KEYS (comma-separated), MARKETAUX_API_KEY, and MARKETAUX_API_KEY_1..N.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._keys: list[str] = []
        self._current_index: int = 0
        self._exhausted_dates: dict[str, str] = {}  # key -> YYYY-MM-DD
        self.reload_keys()

    def reload_keys(self) -> None:
        with self._lock:
            keys: list[str] = []
            plural = os.getenv("MARKETAUX_API_KEYS", "")
            if plural:
                for k in plural.split(","):
                    k_clean = k.strip()
                    if k_clean and k_clean not in keys:
                        keys.append(k_clean)
            singular = os.getenv("MARKETAUX_API_KEY", "").strip()
            if singular and singular not in keys:
                keys.append(singular)
            for i in range(1, 10):
                k_i = os.getenv(f"MARKETAUX_API_KEY_{i}", "").strip()
                if k_i and k_i not in keys:
                    keys.append(k_i)
            self._keys = keys
            self._current_index = 0
            if keys:
                masked = [_mask_key(k) for k in keys]
                logger.info("[MarketauxKeyPool] Initialized with %d Marketaux key(s): %s", len(keys), ", ".join(masked))
            else:
                logger.warning("[MarketauxKeyPool] No Marketaux API keys configured.")

    @property
    def has_keys(self) -> bool:
        with self._lock:
            return len(self._keys) > 0

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._keys)

    def is_key_exhausted_today(self, key: str) -> bool:
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            return self._exhausted_dates.get(key) == today_utc

    def all_keys_exhausted_today(self) -> bool:
        with self._lock:
            if not self._keys:
                return False
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return all(self._exhausted_dates.get(k) == today_utc for k in self._keys)

    def mark_key_exhausted(self, key: str) -> None:
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            self._exhausted_dates[key] = today_utc
            logger.warning("[MarketauxKeyPool] Key %s marked daily quota exhausted for %s", _mask_key(key), today_utc)

    def get_exhausted_dict(self) -> dict[str, str]:
        with self._lock:
            return dict(self._exhausted_dates)

    def set_exhausted_dict(self, data: dict[str, str]) -> None:
        with self._lock:
            if isinstance(data, dict):
                self._exhausted_dates.update(data)

    def get_candidate_keys(self) -> list[str]:
        """Returns keys starting from current index, prioritizing keys not exhausted today."""
        with self._lock:
            if not self._keys:
                return []
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            ordered = [self._keys[(self._current_index + i) % len(self._keys)] for i in range(len(self._keys))]
            unexhausted = [k for k in ordered if self._exhausted_dates.get(k) != today_utc]
            exhausted = [k for k in ordered if self._exhausted_dates.get(k) == today_utc]
            return unexhausted + exhausted

    def set_active_key(self, key: str) -> None:
        with self._lock:
            if key in self._keys:
                self._current_index = self._keys.index(key)


_marketaux_pool = MarketauxKeyPool()


def _load_cache_from_disk():
    global _ARTICLE_CACHE, _LAST_FETCH_TIME, _CACHE_STATUS, _current_page, _DAILY_QUOTA_DATE
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            _ARTICLE_CACHE = data.get("articles", {})
            _LAST_FETCH_TIME = data.get("last_fetch_time")
            _CACHE_STATUS = data.get("status", "ok")
            _current_page = data.get("current_page", 1)
            _DAILY_QUOTA_DATE = data.get("daily_quota_date")
            exhausted = data.get("exhausted_keys", {})
            if isinstance(exhausted, dict):
                _marketaux_pool.set_exhausted_dict(exhausted)
            logger.info(f"[Marketaux] Loaded {len(_ARTICLE_CACHE)} cached articles from disk.")
        except Exception as exc:
            logger.warning(f"[Marketaux] Failed loading cache from disk: {exc}")


def _save_cache_to_disk():
    try:
        payload = {
            "articles": _ARTICLE_CACHE,
            "last_fetch_time": _LAST_FETCH_TIME,
            "status": _CACHE_STATUS,
            "current_page": _current_page,
            "daily_quota_date": _DAILY_QUOTA_DATE,
            "exhausted_keys": _marketaux_pool.get_exhausted_dict(),
        }
        CACHE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"[Marketaux] Failed saving cache to disk: {exc}")


_load_cache_from_disk()


def _get_api_key() -> str:
    candidates = _marketaux_pool.get_candidate_keys()
    return candidates[0] if candidates else ""


def _is_daily_quota_active() -> bool:
    return _marketaux_pool.all_keys_exhausted_today()


def fetch_marketaux_news(force: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Fetches news from Marketaux respecting rate limits, quota, multiple API keys, and disk caching.
    Returns (items_list, meta_dict).
    """
    global _LAST_FETCH_TIME, _CACHE_STATUS, _current_page, _DAILY_QUOTA_DATE

    if not _marketaux_pool.has_keys:
        _CACHE_STATUS = "not_configured"
        return list(_ARTICLE_CACHE.values()), {
            "status": "not_configured",
            "fetched_at": _format_fetched_at(_LAST_FETCH_TIME),
            "total_cached": len(_ARTICLE_CACHE),
        }

    now = time.time()
    with _lock:
        # Check quota lockout for today across all keys
        if _marketaux_pool.all_keys_exhausted_today():
            _CACHE_STATUS = "daily_quota_reached"
            return list(_ARTICLE_CACHE.values()), {
                "status": "daily_quota_reached",
                "fetched_at": _format_fetched_at(_LAST_FETCH_TIME),
                "total_cached": len(_ARTICLE_CACHE),
            }

        # Server-side cooldown: even if force=True, enforce 30s minimum interval
        if _LAST_FETCH_TIME and (now - _LAST_FETCH_TIME < MIN_MANUAL_COOLDOWN_SECONDS):
            return list(_ARTICLE_CACHE.values()), {
                "status": _CACHE_STATUS,
                "fetched_at": _format_fetched_at(_LAST_FETCH_TIME),
                "total_cached": len(_ARTICLE_CACHE),
                "cooldown": True,
            }

        # If not force and cache is still within normal interval, return cache
        if not force and _LAST_FETCH_TIME and (now - _LAST_FETCH_TIME < REFRESH_INTERVAL_SECONDS) and _ARTICLE_CACHE:
            return list(_ARTICLE_CACHE.values()), {
                "status": _CACHE_STATUS,
                "fetched_at": _format_fetched_at(_LAST_FETCH_TIME),
                "total_cached": len(_ARTICLE_CACHE),
            }

        candidates = [k for k in _marketaux_pool.get_candidate_keys() if not _marketaux_pool.is_key_exhausted_today(k)]
        if not candidates:
            _CACHE_STATUS = "daily_quota_reached"
            _DAILY_QUOTA_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _save_cache_to_disk()
            return list(_ARTICLE_CACHE.values()), {
                "status": "daily_quota_reached",
                "fetched_at": _format_fetched_at(_LAST_FETCH_TIME),
                "total_cached": len(_ARTICLE_CACHE),
            }

        success = False
        iso_now = datetime.now(timezone.utc).isoformat()
        last_status_code = None

        for attempt_idx, candidate_key in enumerate(candidates):
            params = {
                "api_token": candidate_key,
                "language": "en",
                "countries": "in",
                "filter_entities": "true",
                "sort": "published_desc",
                "limit": 3,
                "page": _current_page,
            }

            try:
                with httpx.Client(timeout=10.0) as client:
                    res = client.get(MARKETAUX_BASE_URL, params=params)

                last_status_code = res.status_code

                if res.status_code == 200:
                    data = res.json()
                    articles = data.get("data", [])
                    new_uuids_count = 0

                    for item in articles:
                        uuid = item.get("uuid") or item.get("url") or str(time.time())
                        if uuid not in _ARTICLE_CACHE:
                            new_uuids_count += 1
                        _ARTICLE_CACHE[uuid] = {
                            "uuid": uuid,
                            "title": item.get("title", ""),
                            "description": item.get("description", "") or item.get("snippet", ""),
                            "snippet": item.get("snippet", ""),
                            "url": item.get("url", ""),
                            "source": item.get("source", "Marketaux"),
                            "published_at": item.get("published_at", iso_now),
                            "entities": [e.get("name") for e in item.get("entities", []) if isinstance(e, dict) and e.get("name")],
                            "image_url": item.get("image_url"),
                        }

                    # Maintain max cache size (keep newest by published_at)
                    if len(_ARTICLE_CACHE) > MAX_CACHE_ITEMS:
                        sorted_keys = sorted(
                            _ARTICLE_CACHE.keys(),
                            key=lambda k: _ARTICLE_CACHE[k].get("published_at", ""),
                            reverse=True
                        )
                        pruned = {k: _ARTICLE_CACHE[k] for k in sorted_keys[:MAX_CACHE_ITEMS]}
                        _ARTICLE_CACHE.clear()
                        _ARTICLE_CACHE.update(pruned)

                    _CACHE_STATUS = "ok"
                    _LAST_FETCH_TIME = now
                    _current_page = (_current_page % 5) + 1
                    _marketaux_pool.set_active_key(candidate_key)
                    _save_cache_to_disk()

                    logger.info(
                        f"[Marketaux Refresh] timestamp={iso_now}, key={_mask_key(candidate_key)}, "
                        f"HTTP={res.status_code}, returned={len(articles)}, new_uuids_added={new_uuids_count}, "
                        f"total_cached={len(_ARTICLE_CACHE)}, next_page={_current_page}"
                    )
                    success = True
                    break

                elif res.status_code == 402:
                    _marketaux_pool.mark_key_exhausted(candidate_key)
                    logger.warning(
                        f"[Marketaux Refresh] timestamp={iso_now}, key={_mask_key(candidate_key)}, "
                        f"HTTP=402 Daily quota reached for this key. Attempting failover ({attempt_idx + 1}/{len(candidates)})..."
                    )
                    continue

                elif res.status_code == 429:
                    logger.warning(
                        f"[Marketaux Refresh] timestamp={iso_now}, key={_mask_key(candidate_key)}, "
                        f"HTTP=429 Rate limited. Attempting next key ({attempt_idx + 1}/{len(candidates)})..."
                    )
                    continue

                elif res.status_code == 401:
                    logger.warning(
                        f"[Marketaux Refresh] timestamp={iso_now}, key={_mask_key(candidate_key)}, "
                        f"HTTP=401 Invalid API token. Attempting next key ({attempt_idx + 1}/{len(candidates)})..."
                    )
                    continue

                else:
                    logger.warning(
                        f"[Marketaux Refresh] timestamp={iso_now}, key={_mask_key(candidate_key)}, "
                        f"HTTP={res.status_code}: {res.text[:150]}"
                    )
                    continue

            except Exception as exc:
                logger.error(f"[Marketaux] Fetch error with key {_mask_key(candidate_key)}: {exc}")
                continue

        if not success:
            if _marketaux_pool.all_keys_exhausted_today():
                _CACHE_STATUS = "daily_quota_reached"
                _DAILY_QUOTA_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            elif last_status_code == 429:
                _CACHE_STATUS = "rate_limited"
            elif last_status_code == 401:
                _CACHE_STATUS = "invalid_key"
            else:
                _CACHE_STATUS = "error"
            _LAST_FETCH_TIME = now
            _save_cache_to_disk()

    return list(_ARTICLE_CACHE.values()), {
        "status": _CACHE_STATUS,
        "fetched_at": _format_fetched_at(_LAST_FETCH_TIME),
        "total_cached": len(_ARTICLE_CACHE),
    }


def get_cached_suggested_news() -> dict[str, Any]:
    """Returns items and metadata directly from cache (sorted by published_at descending)."""
    items, meta = fetch_marketaux_news(force=False)
    sorted_items = sorted(
        items,
        key=lambda x: x.get("published_at", ""),
        reverse=True
    )
    return {
        "items": sorted_items,
        "meta": meta,
        "source": "Marketaux",
    }


def _format_fetched_at(ts: Optional[float]) -> str:
    if not ts:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── Background Worker ─────────────────────────────────────────────────────────

def start_marketaux_background_worker():
    """Starts a daemon thread to refresh Marketaux news respecting intervals and startup rules."""
    key = _get_api_key()
    logger.info(f"[Marketaux Worker] MARKETAUX_API_KEY is {'set' if bool(key) else 'NOT set'}")
    if not key:
        return

    def _worker():
        # Startup check: only fetch if cache is empty or older than 30 min (REFRESH_INTERVAL_SECONDS)
        now = time.time()
        should_fetch_on_start = (
            len(_ARTICLE_CACHE) == 0
            or _LAST_FETCH_TIME is None
            or (now - _LAST_FETCH_TIME >= REFRESH_INTERVAL_SECONDS)
        )
        if should_fetch_on_start and not _is_daily_quota_active():
            try:
                fetch_marketaux_news(force=True)
            except Exception as e:
                logger.error(f"[Marketaux Worker] Startup fetch error: {e}")

        while True:
            time.sleep(REFRESH_INTERVAL_SECONDS)
            try:
                if not _is_daily_quota_active() and _get_api_key():
                    fetch_marketaux_news(force=True)
            except Exception as e:
                logger.error(f"[Marketaux Worker] Scheduled refresh error: {e}")

    t = threading.Thread(target=_worker, daemon=True, name="MarketauxRefresher")
    t.start()
