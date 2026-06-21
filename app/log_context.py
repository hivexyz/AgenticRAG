"""轻量请求上下文，避免 observability/logger 循环依赖。"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, Optional

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
path_var: ContextVar[Optional[str]] = ContextVar("path", default=None)
method_var: ContextVar[Optional[str]] = ContextVar("method", default=None)
tenant_id_var: ContextVar[Optional[str]] = ContextVar("tenant_id", default=None)


def bind_request_context(*, request_id: str, path: str, method: str, tenant_id: Optional[str] = None) -> None:
    request_id_var.set(request_id)
    path_var.set(path)
    method_var.set(method)
    if tenant_id is not None:
        tenant_id_var.set(tenant_id)


def set_tenant_id(tenant_id: Optional[str]) -> None:
    tenant_id_var.set(tenant_id)


def clear_request_context() -> None:
    request_id_var.set(None)
    path_var.set(None)
    method_var.set(None)
    tenant_id_var.set(None)


def current_request_context() -> Dict[str, Any]:
    return {
        "request_id": request_id_var.get(),
        "path": path_var.get(),
        "method": method_var.get(),
        "tenant_id": tenant_id_var.get(),
    }
