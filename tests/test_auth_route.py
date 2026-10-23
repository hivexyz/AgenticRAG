from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.routes import auth as auth_route


def create_app():
    app = FastAPI()
    app.include_router(auth_route.router, prefix="/auth")
    return app


def test_auth_me_returns_anonymous_context():
    auth_module.api_key_auth.enabled = False
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/auth/me")

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "default"
    assert data["authenticated"] is False
    assert data["can_write"] is True


def test_auth_me_returns_api_key_scopes():
    auth_module.api_key_auth.enabled = True
    auth_module.api_key_auth._mapping = {"read-key": "tenant_a"}
    auth_module.api_key_auth._scopes = {"read-key": frozenset({"read"})}
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/auth/me", headers={"X-API-Key": "read-key"})

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "tenant_a"
    assert data["authenticated"] is True
    assert data["scopes"] == ["read"]
    assert data["can_write"] is False
    assert data["auth_method"] == "api_key"


def test_auth_me_returns_trusted_oidc_context(monkeypatch):
    monkeypatch.setattr(auth_module.settings, "OIDC_TRUSTED_HEADER_ENABLED", True)
    auth_module.api_key_auth.enabled = True
    app = create_app()

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={
                "X-OIDC-Sub": "user@example.com",
                "X-OIDC-Tenant": "Tenant-A",
                "X-OIDC-Scopes": "read write",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "tenant_a"
    assert data["authenticated"] is True
    assert data["auth_method"] == "oidc_trusted_header"
    assert data["subject"] == "user@example.com"
    assert data["can_write"] is True
