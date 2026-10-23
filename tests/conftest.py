import pytest

import app.auth as auth_module
from app.services.cache import cache_registry
from app.services.tenant_limits import tenant_limits


@pytest.fixture(autouse=True)
def reset_api_key_auth_state():
    original_enabled = auth_module.api_key_auth.enabled
    original_mapping = dict(auth_module.api_key_auth._mapping)
    original_scopes = dict(getattr(auth_module.api_key_auth, '_scopes', {}))
    try:
        yield
    finally:
        auth_module.api_key_auth.enabled = original_enabled
        auth_module.api_key_auth._mapping = original_mapping
        auth_module.api_key_auth._scopes = original_scopes
        cache_registry.clear()
        tenant_limits.reset()
