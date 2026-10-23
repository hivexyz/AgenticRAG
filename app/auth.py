"""最小认证鉴权模块：基于 API Key 绑定 tenant 与读写权限。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

from fastapi import Depends, Header, HTTPException, status

from app.config import settings
from app.log_context import set_tenant_id
from app.services.tenant_limits import TenantLimitExceeded, tenant_limits
from app.utils.tenancy import require_tenant_id, validate_tenant_id


@dataclass(frozen=True)
class AuthContext:
    api_key_name: str
    tenant_id: str
    authenticated: bool
    scopes: Tuple[str, ...] = ("read", "write")
    auth_method: str = "anonymous"
    subject: Optional[str] = None

    @property
    def can_write(self) -> bool:
        return "write" in self.scopes or "admin" in self.scopes


class APIKeyAuth:
    def __init__(self) -> None:
        self.enabled = settings.AUTH_ENABLED
        self._mapping, self._scopes = self._parse_mapping(settings.AUTH_API_KEYS)

    @staticmethod
    def _normalize_scopes(raw: str) -> FrozenSet[str]:
        normalized = (raw or "write").strip().lower()
        if normalized in {"readonly", "read_only", "ro"}:
            normalized = "read"
        if normalized in {"rw", "write"}:
            return frozenset({"read", "write"})
        if normalized == "admin":
            return frozenset({"read", "write", "admin"})
        scopes = {item.strip().lower() for item in normalized.replace("+", "|").split("|") if item.strip()}
        if "admin" in scopes:
            scopes.update({"read", "write"})
        if "write" in scopes:
            scopes.add("read")
        return frozenset(scopes & {"read", "write", "admin"}) or frozenset({"read"})

    @classmethod
    def _parse_mapping(cls, raw: str) -> tuple[Dict[str, str], Dict[str, FrozenSet[str]]]:
        mapping: Dict[str, str] = {}
        scopes_by_key: Dict[str, FrozenSet[str]] = {}
        for item in (raw or "").split(","):
            item = item.strip()
            if not item or ":" not in item:
                continue
            parts = item.split(":")
            api_key = parts[0].strip()
            tenant_id = parts[1].strip() if len(parts) > 1 else ""
            scopes = cls._normalize_scopes(parts[2]) if len(parts) > 2 else cls._normalize_scopes("write")
            api_key = api_key.strip()
            if api_key and tenant_id:
                mapping[api_key] = validate_tenant_id(tenant_id)
                scopes_by_key[api_key] = scopes
        return mapping, scopes_by_key

    def authenticate(self, api_key: Optional[str]) -> AuthContext:
        if not self.enabled:
            return AuthContext(
                api_key_name="anonymous",
                tenant_id=validate_tenant_id(settings.DEFAULT_TENANT_ID),
                authenticated=False,
                scopes=("read", "write"),
                auth_method="anonymous",
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
        scopes = tuple(sorted(self._scopes.get(api_key, frozenset({"read", "write"}))))
        return AuthContext(
            api_key_name=api_key[:4] + "***",
            tenant_id=tenant_id,
            authenticated=True,
            scopes=scopes,
            auth_method="api_key",
        )

    def authenticate_trusted_oidc_headers(
        self,
        *,
        subject: Optional[str],
        tenant_id: Optional[str],
        scopes_header: Optional[str],
    ) -> Optional[AuthContext]:
        if not settings.OIDC_TRUSTED_HEADER_ENABLED:
            return None
        if not subject or not tenant_id:
            return None
        raw_scopes = (scopes_header or "read").replace(",", "|").replace(" ", "|")
        scopes = tuple(sorted(self._normalize_scopes(raw_scopes)))
        return AuthContext(
            api_key_name=f"oidc:{subject[:12]}",
            tenant_id=validate_tenant_id(tenant_id),
            authenticated=True,
            scopes=scopes,
            auth_method="oidc_trusted_header",
            subject=subject,
        )


def validate_auth_startup_policy() -> None:
    """生产环境必须显式开启认证，或显式允许匿名访问。"""
    if (
        settings.is_production
        and not settings.AUTH_ENABLED
        and not settings.OIDC_TRUSTED_HEADER_ENABLED
        and not settings.AUTH_ALLOW_ANONYMOUS
    ):
        raise RuntimeError("生产环境必须开启 AUTH_ENABLED/OIDC_TRUSTED_HEADER_ENABLED，或显式设置 AUTH_ALLOW_ANONYMOUS=true")


api_key_auth = APIKeyAuth()


async def get_auth_context(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_oidc_sub: Optional[str] = Header(None, alias="X-OIDC-Sub"),
    x_oidc_tenant: Optional[str] = Header(None, alias="X-OIDC-Tenant"),
    x_oidc_scopes: Optional[str] = Header(None, alias="X-OIDC-Scopes"),
) -> AuthContext:
    if x_api_key:
        auth = api_key_auth.authenticate(x_api_key)
    else:
        auth = api_key_auth.authenticate_trusted_oidc_headers(
            subject=x_oidc_sub,
            tenant_id=x_oidc_tenant,
            scopes_header=x_oidc_scopes,
        )
        if auth is None:
            auth = api_key_auth.authenticate(x_api_key)
    set_tenant_id(auth.tenant_id)
    try:
        tenant_limits.check_request(auth.tenant_id)
        tenant_limits.check_token_quota(auth.tenant_id)
    except TenantLimitExceeded as exc:
        headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else None
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=exc.detail, headers=headers) from exc
    return auth


async def get_tenant_id(auth: AuthContext = Depends(get_auth_context)) -> str:
    set_tenant_id(auth.tenant_id)
    return auth.tenant_id


async def require_write_access(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if not auth.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前 API Key 没有写权限",
        )
    return auth


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
