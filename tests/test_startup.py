from fastapi.testclient import TestClient

import app.main as main_module


def test_app_startup_runs_vector_store_connect_and_ensure_ready(monkeypatch):
    events = []

    async def fake_init_db():
        events.append('postgres.init_db')

    async def fake_close_db():
        events.append('postgres.close_db')

    def fake_vector_store_connect():
        events.append('vector_store.connect')

    async def fake_vector_store_ensure_ready():
        events.append('vector_store.ensure_ready')

    def fake_vector_store_disconnect():
        events.append('vector_store.disconnect')

    def fake_llm_connect():
        events.append('llm.connect')

    def fake_llm_disconnect():
        events.append('llm.disconnect')

    def fake_embedding_connect():
        events.append('embedding.connect')

    def fake_embedding_disconnect():
        events.append('embedding.disconnect')

    def fake_reranker_connect():
        events.append('reranker.connect')

    def fake_reranker_disconnect():
        events.append('reranker.disconnect')

    def fake_build_graph():
        events.append('agentic_rag.build_graph')

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

    with TestClient(main_module.app) as client:
        response = client.get('/')

    assert response.status_code == 200
    assert events.index('vector_store.connect') < events.index('vector_store.ensure_ready')
    assert 'postgres.init_db' in events
    assert 'agentic_rag.build_graph' in events
    assert 'vector_store.disconnect' in events
