from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.log_context import bind_request_context, clear_request_context
from app.observability import generate_request_id, metrics_registry, RequestTimer


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or generate_request_id()
        timer = RequestTimer()
        bind_request_context(request_id=request_id, path=request.url.path, method=request.method)
        try:
            response = await call_next(request)
        finally:
            pass
        latency_ms = timer.elapsed_ms()
        response.headers["X-Request-ID"] = request_id
        metrics_registry.record_request(
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )
        clear_request_context()
        return response
