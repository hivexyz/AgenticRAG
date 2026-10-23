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


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_line(name: str, value: float | int, labels: Optional[Dict[str, str]] = None) -> str:
    if labels:
        rendered_labels = ",".join(f'{key}="{_escape_label(label_value)}"' for key, label_value in sorted(labels.items()))
        return f"{name}{{{rendered_labels}}} {value}"
    return f"{name} {value}"


def render_prometheus_metrics(
    *,
    metrics: Dict[str, Any],
    tenant_token_usage: Dict[str, int],
    cache_stats: Optional[Dict[str, Dict[str, Any]]] = None,
    token_cost_per_1k: float = 0.0,
) -> str:
    """Render in-process metrics as Prometheus text exposition format."""
    lines: list[str] = [
        "# HELP agenticrag_http_requests_total Total HTTP requests handled by this process.",
        "# TYPE agenticrag_http_requests_total counter",
        _metric_line("agenticrag_http_requests_total", int(metrics.get("request_count") or 0)),
        "# HELP agenticrag_http_errors_total Total HTTP requests with status code >= 400.",
        "# TYPE agenticrag_http_errors_total counter",
        _metric_line("agenticrag_http_errors_total", int(metrics.get("error_count") or 0)),
        "# HELP agenticrag_http_path_requests_total HTTP requests by path and method.",
        "# TYPE agenticrag_http_path_requests_total counter",
    ]

    path_counts = metrics.get("path_counts") or {}
    method_counts = metrics.get("method_counts") or {}
    method_label = ",".join(sorted(method_counts.keys())) or "unknown"
    for path, count in sorted(path_counts.items()):
        lines.append(_metric_line(
            "agenticrag_http_path_requests_total",
            int(count),
            {"path": str(path), "methods": method_label},
        ))

    lines.extend([
        "# HELP agenticrag_http_request_latency_average_ms Average request latency by path in milliseconds.",
        "# TYPE agenticrag_http_request_latency_average_ms gauge",
    ])
    for path, latency_ms in sorted((metrics.get("average_latency_ms") or {}).items()):
        lines.append(_metric_line(
            "agenticrag_http_request_latency_average_ms",
            float(latency_ms),
            {"path": str(path)},
        ))

    lines.extend([
        "# HELP agenticrag_tenant_token_usage_total LLM token usage by tenant and UTC day.",
        "# TYPE agenticrag_tenant_token_usage_total counter",
    ])
    for raw_key, tokens in sorted(tenant_token_usage.items()):
        tenant_id, _, day = str(raw_key).partition(":")
        lines.append(_metric_line(
            "agenticrag_tenant_token_usage_total",
            int(tokens),
            {"tenant_id": tenant_id, "day": day or "unknown"},
        ))

    lines.extend([
        "# HELP agenticrag_tenant_estimated_model_cost_usd Estimated model cost by tenant and UTC day.",
        "# TYPE agenticrag_tenant_estimated_model_cost_usd gauge",
    ])
    for raw_key, tokens in sorted(tenant_token_usage.items()):
        tenant_id, _, day = str(raw_key).partition(":")
        estimated_cost = (int(tokens) / 1000.0) * float(token_cost_per_1k or 0.0)
        lines.append(_metric_line(
            "agenticrag_tenant_estimated_model_cost_usd",
            round(estimated_cost, 8),
            {"tenant_id": tenant_id, "day": day or "unknown"},
        ))

    lines.extend([
        "# HELP agenticrag_cache_hits_total Cache hits by cache name.",
        "# TYPE agenticrag_cache_hits_total counter",
    ])
    for name, stats in sorted((cache_stats or {}).items()):
        lines.append(_metric_line("agenticrag_cache_hits_total", int(stats.get("hits") or 0), {"cache": name}))

    lines.extend([
        "# HELP agenticrag_cache_misses_total Cache misses by cache name.",
        "# TYPE agenticrag_cache_misses_total counter",
    ])
    for name, stats in sorted((cache_stats or {}).items()):
        lines.append(_metric_line("agenticrag_cache_misses_total", int(stats.get("misses") or 0), {"cache": name}))

    lines.extend([
        "# HELP agenticrag_cache_hit_rate Cache hit rate by cache name.",
        "# TYPE agenticrag_cache_hit_rate gauge",
    ])
    for name, stats in sorted((cache_stats or {}).items()):
        lines.append(_metric_line("agenticrag_cache_hit_rate", float(stats.get("hit_rate") or 0.0), {"cache": name}))

    return "\n".join(lines) + "\n"


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
