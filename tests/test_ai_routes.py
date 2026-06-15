from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.routes import ai as ai_module


def create_app():
    app = FastAPI()
    app.include_router(ai_module.router, prefix='/ai')
    return app


def test_search_with_rerank_requires_api_key(monkeypatch):
    auth_module.api_key_auth.enabled = True
    auth_module.api_key_auth._mapping = {"valid-key": "tenant_a"}
    app = create_app()

    with TestClient(app) as client:
        response = client.post('/ai/search', json={
            'query': 'test',
            'top_k': 3,
            'rerank_top_k': 2,
        })

    assert response.status_code == 401
    assert response.json()['detail'] == '缺少 API Key'


def test_search_with_rerank_uses_tenant_from_api_key(monkeypatch):
    auth_module.api_key_auth.enabled = True
    auth_module.api_key_auth._mapping = {"valid-key": "tenant_a"}
    app = create_app()
    captured = {}

    async def fake_create_embedding(_query):
        return [0.1, 0.2]

    async def fake_search_vectors(query_vectors, top_k, tenant_id=None, **kwargs):
        captured['tenant_id'] = tenant_id
        return [[]]

    monkeypatch.setattr(ai_module.embedding_manager, 'create_embedding', fake_create_embedding)
    monkeypatch.setattr(ai_module.vector_store, 'search_vectors', fake_search_vectors)

    with TestClient(app) as client:
        response = client.post('/ai/search', json={
            'query': 'test',
            'top_k': 3,
            'rerank_top_k': 2,
        }, headers={'X-API-Key': 'valid-key'})

    assert response.status_code == 200
    assert captured['tenant_id'] == 'tenant_a'


def test_search_with_rerank_returns_503_when_embedding_unavailable(monkeypatch):
    auth_module.api_key_auth.enabled = False
    app = create_app()

    async def fake_create_embedding(_query):
        raise RuntimeError('Embedding 客户端未初始化')

    monkeypatch.setattr(ai_module.embedding_manager, 'create_embedding', fake_create_embedding)

    with TestClient(app) as client:
        response = client.post('/ai/search', json={
            'query': 'test',
            'top_k': 3,
            'rerank_top_k': 2,
        })

    assert response.status_code == 503
    assert response.json()['detail'] == 'Embedding 客户端未初始化'
