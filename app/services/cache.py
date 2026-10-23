"""Small in-process TTL caches for model-adjacent hot paths."""
from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0

    @property
    def requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return 0.0 if self.requests == 0 else self.hits / self.requests


class TTLCache:
    def __init__(self, *, name: str, max_size: int, ttl_seconds: float) -> None:
        self.name = name
        self.max_size = max(int(max_size), 0)
        self.ttl_seconds = max(float(ttl_seconds), 0.0)
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._stats = CacheStats()
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._stats = CacheStats()

    def get(self, key: str) -> Optional[Any]:
        if self.max_size <= 0 or self.ttl_seconds <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                self._stats.misses += 1
                return None
            expires_at, value = item
            if expires_at <= now:
                self._items.pop(key, None)
                self._stats.misses += 1
                self._stats.evictions += 1
                return None
            self._items.move_to_end(key)
            self._stats.hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        if self.max_size <= 0 or self.ttl_seconds <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._items[key] = (now + self.ttl_seconds, value)
            self._items.move_to_end(key)
            self._stats.sets += 1
            while len(self._items) > self.max_size:
                self._items.popitem(last=False)
                self._stats.evictions += 1

    def snapshot(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            expired = [key for key, (expires_at, _) in self._items.items() if expires_at <= now]
            for key in expired:
                self._items.pop(key, None)
                self._stats.evictions += 1
            return {
                "name": self.name,
                "size": len(self._items),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds,
                "hits": self._stats.hits,
                "misses": self._stats.misses,
                "sets": self._stats.sets,
                "evictions": self._stats.evictions,
                "hit_rate": self._stats.hit_rate,
            }


class CacheRegistry:
    def __init__(self) -> None:
        self._caches: Dict[str, TTLCache] = {}

    def register(self, cache: TTLCache) -> TTLCache:
        self._caches[cache.name] = cache
        return cache

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {name: cache.snapshot() for name, cache in sorted(self._caches.items())}

    def clear(self) -> None:
        for cache in self._caches.values():
            cache.clear()


cache_registry = CacheRegistry()
