"""Authentication context API."""
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import AuthContext, get_auth_context

router = APIRouter()


class AuthMeResponse(BaseModel):
    tenant_id: str
    authenticated: bool
    api_key_name: str
    scopes: List[str]
    can_write: bool
    auth_method: str
    subject: str | None = None


@router.get("/me", response_model=AuthMeResponse)
async def get_current_auth_context(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, object]:
    return {
        "tenant_id": auth.tenant_id,
        "authenticated": auth.authenticated,
        "api_key_name": auth.api_key_name,
        "scopes": list(auth.scopes),
        "can_write": auth.can_write,
        "auth_method": auth.auth_method,
        "subject": auth.subject,
    }
