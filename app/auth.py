"""最小认证鉴权模块：基于 API Key 绑定 tenant。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import Depends, Header, HTTPException, status

from app.config import settings
from app.log_context import set_tenant_id
from app.utils.tenancy import require_tenant_id, validate_tenant_id


@dataclass(frozen=True)
class AuthContext:
    api_key_name: str
    tenant_id: str
    authenticated: bool


class APIKeyAuth:
    def __init__(self) -> None:
        self.enabled = settings.AUTH_ENABLED
        self._mapping = self._parse_mapping(settings.AUTH_API_KEYS)

    @staticmethod
    def _parse_mapping(raw: str) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for item in (raw or "").split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            api_key, tenant_id = item.split(":", 1)
            api_key = api_key.strip()
            tenant_id = tenant_id.strip()
            if api_key and tenant_id:
                mapping[api_key] = validate_tenant_id(tenant_id)
        return mapping

    def authenticate(self, api_key: Optional[str]) -> AuthContext:
        if not self.enabled:
            return AuthContext(
                api_key_name="anonymous",
                tenant_id=validate_tenant_id(settings.DEFAULT_TENANT_ID),
                authenticated=False,
            )

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少 API Key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        tenant_id = self._mapping.get(api_key)
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 API Key",
                headers={"WWW-Authenticate": "ApiKey"},
            )
        return AuthContext(api_key_name=api_key[:4] + "***", tenant_id=tenant_id, authenticated=True)


api_key_auth = APIKeyAuth()


async def get_auth_context(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> AuthContext:
    return api_key_auth.authenticate(x_api_key)


async def get_tenant_id(auth: AuthContext = Depends(get_auth_context)) -> str:
    set_tenant_id(auth.tenant_id)
    return auth.tenant_id


def resolve_tenant_id(explicit_tenant_id: Optional[str], auth: AuthContext) -> str:
    """认证开启时只信任服务端 tenant；关闭时兼容旧接口显式 tenant_id。"""
    if auth.authenticated:
        set_tenant_id(auth.tenant_id)
        return auth.tenant_id
    if explicit_tenant_id:
        tenant_id = require_tenant_id(explicit_tenant_id)
        set_tenant_id(tenant_id)
        return tenant_id
    set_tenant_id(auth.tenant_id)
    return auth.tenant_id
