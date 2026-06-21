"""P1 第一轮：request_id、结构化日志、审计日志、metrics 基础设施。"""
from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, Optional

from app.log_context import current_request_context
from app.utils.logger import logger


class MetricsRegistry:
    def __init__(self) -> None:
        self.request_count = 0
        self.error_count = 0
        self.path_counts: Dict[str, int] = defaultdict(int)
        self.method_counts: Dict[str, int] = defaultdict(int)
        self.latency_ms_total: Dict[str, float] = defaultdict(float)

    def record_request(self, *, path: str, method: str, status_code: int, latency_ms: float) -> None:
        self.request_count += 1
        self.path_counts[path] += 1
        self.method_counts[method] += 1
        self.latency_ms_total[path] += latency_ms
        if status_code >= 400:
            self.error_count += 1

    def snapshot(self) -> Dict[str, Any]:
        average_latency = {
            path: (self.latency_ms_total[path] / count if count else 0.0)
            for path, count in self.path_counts.items()
        }
        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "path_counts": dict(self.path_counts),
            "method_counts": dict(self.method_counts),
            "average_latency_ms": average_latency,
        }


metrics_registry = MetricsRegistry()


def generate_request_id() -> str:
    return uuid.uuid4().hex


def log_audit_event(action: str, *, tenant_id: Optional[str] = None, target_id: Optional[str] = None, result: str = "success", extra: Optional[Dict[str, Any]] = None) -> None:
    payload = {
        "event": "audit",
        "action": action,
        "tenant_id": tenant_id,
        "target_id": target_id,
        "result": result,
        **current_request_context(),
    }
    if extra:
        payload["extra"] = extra
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))


class RequestTimer:
    def __init__(self) -> None:
        self.started = time.perf_counter()

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0
