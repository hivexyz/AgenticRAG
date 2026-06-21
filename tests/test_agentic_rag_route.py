from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth as auth_module
from app.routes import agentic_rag as rag_module


def create_app():
    app = FastAPI()
    app.include_router(rag_module.router, prefix='/ai')
    return app


def test_agentic_rag_query_requires_api_key():
    auth_module.api_key_auth.enabled = True
    auth_module.api_key_auth._mapping = {"valid-key": "tenant_a"}
    app = create_app()

    with TestClient(app) as client:
        response = client.post('/ai/agentic-rag/query', json={'query': '你好'})

    assert response.status_code == 401
    assert response.json()['detail'] == '缺少 API Key'


def test_agentic_rag_query_uses_tenant_from_api_key(monkeypatch):
    auth_module.api_key_auth.enabled = True
    auth_module.api_key_auth._mapping = {"valid-key": "tenant_a"}
    app = create_app()
    captured = {}

    async def fake_query(user_query, tenant_id, conversation_history=None, config=None):
        captured['tenant_id'] = tenant_id
        return {
            'query': user_query,
            'answer': 'ok',
            'quality_score': 1.0,
            'query_analysis': None,
            'search_results': [],
            'reranked_results': [],
            'retrieval_count': 0,
            'context': None,
            'citations': [{'claim': '结论 1', 'sources': [{'title': '制度A'}]}],
            'evidence_cards': [{'snippet': '证据片段'}],
            'answer_blocks': [{'text': '根据制度A，可以这样处理。', 'citation_ids': [1], 'uncertainty_flag': False}],
            'uncertainty': {'label': '资料充分'},
            'refusal': None,
            'messages': [],
            'error': None,
        }

    monkeypatch.setattr(rag_module.agentic_rag_manager, 'query', fake_query)

    with TestClient(app) as client:
        response = client.post('/ai/agentic-rag/query', json={'query': '你好'}, headers={'X-API-Key': 'valid-key'})

    assert response.status_code == 200
    assert captured['tenant_id'] == 'tenant_a'


def test_agentic_rag_query_returns_citations_and_uncertainty(monkeypatch):
    auth_module.api_key_auth.enabled = True
    auth_module.api_key_auth._mapping = {"valid-key": "tenant_a"}
    app = create_app()

    async def fake_query(user_query, tenant_id, conversation_history=None, config=None):
        return {
            'query': user_query,
            'answer': '根据制度A，可以这样处理。【来源1】',
            'quality_score': 0.92,
            'query_analysis': None,
            'search_results': [],
            'reranked_results': [],
            'retrieval_count': 0,
            'context': None,
            'context_status': {'retrieval_doc_count': 1},
            'citations': [{'claim': '结论 1', 'sources': [{'title': '制度A', 'page': 2}]}],
            'evidence_cards': [{'snippet': '制度A 原文片段'}],
            'answer_blocks': [{'text': '根据制度A，可以这样处理。', 'citation_ids': [1], 'uncertainty_flag': False}],
            'uncertainty': {'label': '资料充分'},
            'refusal': None,
            'messages': [],
            'error': None,
        }

    monkeypatch.setattr(rag_module.agentic_rag_manager, 'query', fake_query)

    with TestClient(app) as client:
        response = client.post('/ai/agentic-rag/query', json={'query': '你好'}, headers={'X-API-Key': 'valid-key'})

    assert response.status_code == 200
    data = response.json()
    assert data['citations'][0]['sources'][0]['title'] == '制度A'
    assert data['evidence_cards'][0]['snippet'] == '制度A 原文片段'
    assert data['uncertainty']['label'] == '资料充分'
    assert data['answer_blocks'][0]['citation_ids'] == [1]
