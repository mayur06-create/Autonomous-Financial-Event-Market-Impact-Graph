"""Base utilities for NLP package: device, singletons, LRU hash cache, and fake injection."""
import hashlib
import os
import threading
from typing import Any, Callable, Dict, Optional

_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {}
_MAX_CACHE = 500

# Registry for testing/CI mock injection
_MOCKS: Dict[str, Any] = {}


def get_device() -> str:
    """Return device from env NEWSGRAPH_DEVICE (cpu default)."""
    return os.getenv("NEWSGRAPH_DEVICE", "cpu").strip().lower()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


def cached_result(namespace: str, text: str, compute_fn: Callable[[], Any]) -> Any:
    """Cache inference result by text hash within namespace."""
    key = f"{namespace}:{text_hash(text)}"
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]

    result = compute_fn()

    with _CACHE_LOCK:
        if len(_CACHE) >= _MAX_CACHE:
            # Clear half the cache if full
            for k in list(_CACHE.keys())[: _MAX_CACHE // 2]:
                _CACHE.pop(k, None)
        _CACHE[key] = result
    return result


def register_mock(name: str, instance: Any) -> None:
    """Register a fake/mock engine for unit tests or offline CI."""
    _MOCKS[name] = instance


def clear_mocks() -> None:
    _MOCKS.clear()


def get_mock(name: str) -> Optional[Any]:
    return _MOCKS.get(name)
