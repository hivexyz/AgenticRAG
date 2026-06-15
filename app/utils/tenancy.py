"""多租户辅助函数。"""

from __future__ import annotations

import re

from fastapi import HTTPException

from app.config import settings

_TENANT_PATTERN = re.compile(r"[^a-z0-9_]+")


def normalize_tenant_id(tenant_id: str | None) -> str:
    """规范化租户 ID，用于 collection 名称与过滤。"""
    if tenant_id is None:
        return settings.DEFAULT_TENANT_ID

    candidate = tenant_id.strip().lower()
    if not candidate:
        return settings.DEFAULT_TENANT_ID

    candidate = candidate.replace("-", "_")
    candidate = _TENANT_PATTERN.sub("_", candidate)
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    return candidate


def validate_tenant_id(tenant_id: str | None) -> str:
    """返回规范化后的 tenant_id；非法输入抛出 ValueError。"""
    normalized = normalize_tenant_id(tenant_id)
    if not normalized:
        raise ValueError("tenant_id 格式无效")
    return normalized


def require_tenant_id(tenant_id: str | None) -> str:
    """校验并返回可用 tenant_id。"""
    try:
        return validate_tenant_id(tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="tenant_id 格式无效，只能包含字母、数字、连字符或下划线",
        ) from exc


def build_tenant_collection_name(tenant_id: str) -> str:
    """根据租户生成 collection 名称。"""
    normalized = validate_tenant_id(tenant_id)
    return f"{settings.MILVUS_COLLECTION_NAME}_{normalized}"


def build_tenant_expr(tenant_id: str, expr: str | None = None) -> str:
    """拼接租户过滤表达式。"""
    tenant_expr = f'metadata["tenant_id"] == "{validate_tenant_id(tenant_id)}"'
    if expr:
        return f"({tenant_expr}) and ({expr})"
    return tenant_expr
