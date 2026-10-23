import pytest

from app.auth import APIKeyAuth
from app.services.tenant_limits import TenantLimitExceeded, InMemoryTenantLimits


def test_api_key_auth_parses_backward_compatible_write_scope():
    mapping, scopes = APIKeyAuth._parse_mapping("legacy-key:tenant-a")

    assert mapping["legacy-key"] == "tenant_a"
    assert scopes["legacy-key"] == frozenset({"read", "write"})


def test_api_key_auth_parses_read_only_scope():
    mapping, scopes = APIKeyAuth._parse_mapping("read-key:tenant-a:read,admin-key:tenant-b:admin")

    assert mapping["read-key"] == "tenant_a"
    assert scopes["read-key"] == frozenset({"read"})
    assert scopes["admin-key"] == frozenset({"read", "write", "admin"})


def test_tenant_rate_limit_blocks_after_limit(monkeypatch):
    limiter = InMemoryTenantLimits()
    monkeypatch.setattr("app.services.tenant_limits.settings.TENANT_RATE_LIMIT_PER_MINUTE", 2)

    limiter.check_request("tenant_a", now=100.0)
    limiter.check_request("tenant_a", now=101.0)
    with pytest.raises(TenantLimitExceeded) as exc:
        limiter.check_request("tenant_a", now=102.0)

    assert "请求过于频繁" in exc.value.detail
    assert exc.value.retry_after_seconds is not None


def test_tenant_token_quota_blocks_after_usage(monkeypatch):
    limiter = InMemoryTenantLimits()
    monkeypatch.setattr("app.services.tenant_limits.settings.TENANT_TOKEN_QUOTA_PER_DAY", 10)

    limiter.record_tokens("tenant_a", 10)
    with pytest.raises(TenantLimitExceeded) as exc:
        limiter.check_token_quota("tenant_a")

    assert "token 配额已用尽" in exc.value.detail
