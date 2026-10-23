"""Per-tenant request and token quota guardrails."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Deque, Dict, Optional, Tuple

from app.config import settings


@dataclass
class TenantLimitExceeded(Exception):
    detail: str
    retry_after_seconds: Optional[int] = None


class InMemoryTenantLimits:
    """Small in-process limiter with a narrow API, ready to swap for Redis later."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._request_windows: Dict[str, Deque[float]] = defaultdict(deque)
        self._token_usage: Dict[Tuple[str, str], int] = defaultdict(int)

    def reset(self) -> None:
        with self._lock:
            self._request_windows.clear()
            self._token_usage.clear()

    def check_request(self, tenant_id: str, *, now: Optional[float] = None) -> None:
        limit = int(getattr(settings, "TENANT_RATE_LIMIT_PER_MINUTE", 0) or 0)
        if limit <= 0:
            return
        current = now if now is not None else datetime.utcnow().timestamp()
        window_start = current - 60
        with self._lock:
            bucket = self._request_windows[tenant_id]
            while bucket and bucket[0] <= window_start:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(60 - (current - bucket[0])))
                raise TenantLimitExceeded(
                    detail=f"租户 {tenant_id} 请求过于频繁，请稍后重试",
                    retry_after_seconds=retry_after,
                )
            bucket.append(current)

    def _usage_key(self, tenant_id: str, *, now: Optional[datetime] = None) -> Tuple[str, str]:
        current = now or datetime.utcnow()
        return tenant_id, current.strftime("%Y-%m-%d")

    def check_token_quota(self, tenant_id: str, *, now: Optional[datetime] = None) -> None:
        quota = int(getattr(settings, "TENANT_TOKEN_QUOTA_PER_DAY", 0) or 0)
        if quota <= 0:
            return
        key = self._usage_key(tenant_id, now=now)
        with self._lock:
            used = self._token_usage.get(key, 0)
        if used >= quota:
            raise TenantLimitExceeded(
                detail=f"租户 {tenant_id} 今日 token 配额已用尽",
                retry_after_seconds=None,
            )

    def record_tokens(self, tenant_id: str, token_count: int, *, now: Optional[datetime] = None) -> int:
        tokens = max(int(token_count or 0), 0)
        if tokens <= 0:
            return self.tokens_used(tenant_id, now=now)
        key = self._usage_key(tenant_id, now=now)
        with self._lock:
            self._token_usage[key] += tokens
            return self._token_usage[key]

    def tokens_used(self, tenant_id: str, *, now: Optional[datetime] = None) -> int:
        key = self._usage_key(tenant_id, now=now)
        with self._lock:
            return self._token_usage.get(key, 0)

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {f"{tenant}:{day}": used for (tenant, day), used in self._token_usage.items()}


tenant_limits = InMemoryTenantLimits()
