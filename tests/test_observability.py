from fastapi.testclient import TestClient

import app.main as main_module
from app.observability import metrics_registry


def _patch_startup(monkeypatch):
    async def fake_init_db():
        return None
    async def fake_close_db():
        return None
    def fake_vector_store_connect():
        return None
    async def fake_vector_store_ensure_ready():
        return None
    def fake_vector_store_disconnect():
        return None
    def fake_llm_connect():
        return None
    def fake_llm_disconnect():
        return None
    def fake_embedding_connect():
        return None
    def fake_embedding_disconnect():
        return None
    def fake_reranker_connect():
        return None
    def fake_reranker_disconnect():
        return None
    def fake_build_graph():
        return None

    monkeypatch.setattr(main_module.postgres_manager, 'init_db', fake_init_db)
    monkeypatch.setattr(main_module.postgres_manager, 'close_db', fake_close_db)
    monkeypatch.setattr(main_module.vector_store, 'connect', fake_vector_store_connect)
    monkeypatch.setattr(main_module.vector_store, 'ensure_ready', fake_vector_store_ensure_ready)
    monkeypatch.setattr(main_module.vector_store, 'disconnect', fake_vector_store_disconnect)
    monkeypatch.setattr(main_module.llm_manager, 'connect', fake_llm_connect)
    monkeypatch.setattr(main_module.llm_manager, 'disconnect', fake_llm_disconnect)
    monkeypatch.setattr(main_module.embedding_manager, 'connect', fake_embedding_connect)
    monkeypatch.setattr(main_module.embedding_manager, 'disconnect', fake_embedding_disconnect)
    monkeypatch.setattr(main_module.reranker_manager, 'connect', fake_reranker_connect)
    monkeypatch.setattr(main_module.reranker_manager, 'disconnect', fake_reranker_disconnect)
    monkeypatch.setattr(main_module.agentic_rag_manager, 'build_graph', fake_build_graph)


def test_request_id_header_is_returned(monkeypatch):
    _patch_startup(monkeypatch)
    with TestClient(main_module.app) as client:
        response = client.get('/', headers={'X-Request-ID': 'req-123'})

    assert response.status_code == 200
    assert response.headers['X-Request-ID'] == 'req-123'


def test_metrics_endpoint_returns_counts(monkeypatch):
    _patch_startup(monkeypatch)
    before = metrics_registry.request_count
    with TestClient(main_module.app) as client:
        client.get('/')
        response = client.get('/api/v1/health/metrics')

    assert response.status_code == 200
    data = response.json()
    assert data['request_count'] >= before + 1
    assert 'average_latency_ms' in data
    assert '/' in data['path_counts'] or '/api/v1/health/metrics' in data['path_counts']
