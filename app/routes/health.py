"""
健康检查路由
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import settings
from app.observability import metrics_registry, render_prometheus_metrics
from app.services.cache import cache_registry
from app.services.tenant_limits import tenant_limits

router = APIRouter()


@router.get("/")
async def health_check(request: Request):
    app_status = getattr(request.app.state, "app_status", {})
    ready = request.app.state.is_ready() if hasattr(request.app.state, "is_ready") else True
    payload = {
        "status": "healthy" if ready else "degraded",
        "ready": ready,
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": app_status,
    }
    return payload


@router.get("/ready")
async def readiness_check(request: Request):
    app_status = getattr(request.app.state, "app_status", {})
    ready = request.app.state.is_ready() if hasattr(request.app.state, "is_ready") else True
    payload = {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": app_status,
    }
    if ready:
        return payload
    return JSONResponse(status_code=503, content=payload)


@router.get("/metrics")
async def metrics():
    payload = metrics_registry.snapshot()
    payload["cache"] = cache_registry.snapshot()
    return payload


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
async def prometheus_metrics():
    return PlainTextResponse(
        render_prometheus_metrics(
            metrics=metrics_registry.snapshot(),
            tenant_token_usage=tenant_limits.snapshot(),
            cache_stats=cache_registry.snapshot(),
            token_cost_per_1k=settings.MODEL_COST_PER_1K_TOKENS_USD,
        ),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/ping")
async def ping():
    return {"message": "pong"}
