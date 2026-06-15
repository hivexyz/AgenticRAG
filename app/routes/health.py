"""
健康检查路由
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.observability import metrics_registry

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
    return metrics_registry.snapshot()


@router.get("/ping")
async def ping():
    return {"message": "pong"}
