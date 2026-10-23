from fastapi.testclient import TestClient

import pytest

import app.main as main_module


def test_app_startup_runs_vector_store_connect_and_ensure_ready(monkeypatch):
    events = []

    async def fake_init_db():
        events.append('postgres.init_db')

    async def fake_recover_wiki_compile_jobs(submit_job):
        events.append('wiki.recover_jobs')
        return {'recovered_count': 0, 'job_ids': []}

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
    monkeypatch.setattr(main_module, 'recover_wiki_compile_jobs', fake_recover_wiki_compile_jobs)
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
    assert events.index('postgres.init_db') < events.index('wiki.recover_jobs')
    assert events.index('vector_store.connect') < events.index('vector_store.ensure_ready')
    assert 'postgres.init_db' in events
    assert 'agentic_rag.build_graph' in events
    assert 'vector_store.disconnect' in events


def test_app_startup_skips_inline_wiki_recovery_when_disabled(monkeypatch):
    events = []

    async def fake_init_db():
        events.append('postgres.init_db')

    async def should_not_recover_wiki_compile_jobs(submit_job):
        raise AssertionError('wiki recovery should be handled by standalone worker')

    async def fake_close_db():
        return None

    def fake_vector_store_connect():
        return None

    async def fake_vector_store_ensure_ready():
        return None

    def fake_vector_store_disconnect():
        return None

    def fake_connect():
        return None

    def fake_disconnect():
        return None

    def fake_build_graph():
        return None

    monkeypatch.setattr(main_module.settings, 'WIKI_COMPILE_INLINE_SUBMIT', False)
    monkeypatch.setattr(main_module.postgres_manager, 'init_db', fake_init_db)
    monkeypatch.setattr(main_module, 'recover_wiki_compile_jobs', should_not_recover_wiki_compile_jobs)
    monkeypatch.setattr(main_module.postgres_manager, 'close_db', fake_close_db)
    monkeypatch.setattr(main_module.vector_store, 'connect', fake_vector_store_connect)
    monkeypatch.setattr(main_module.vector_store, 'ensure_ready', fake_vector_store_ensure_ready)
    monkeypatch.setattr(main_module.vector_store, 'disconnect', fake_vector_store_disconnect)
    monkeypatch.setattr(main_module.llm_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.llm_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.embedding_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.embedding_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.reranker_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.reranker_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.agentic_rag_manager, 'build_graph', fake_build_graph)

    with TestClient(main_module.app) as client:
        response = client.get('/')

    assert response.status_code == 200
    assert events == ['postgres.init_db']


def test_app_startup_fails_fast_when_production_auth_is_anonymous(monkeypatch):
    monkeypatch.setattr(main_module.settings, 'ENVIRONMENT', 'production')
    monkeypatch.setattr(main_module.settings, 'AUTH_ENABLED', False)
    monkeypatch.setattr(main_module.settings, 'AUTH_ALLOW_ANONYMOUS', False)

    with pytest.raises(RuntimeError, match='生产环境必须开启 AUTH_ENABLED'):
        with TestClient(main_module.app):
            pass


def test_app_startup_allows_explicit_anonymous_production(monkeypatch):
    events = []

    async def fake_init_db():
        events.append('postgres.init_db')

    async def fake_recover_wiki_compile_jobs(submit_job):
        return {'recovered_count': 0, 'job_ids': []}

    async def fake_close_db():
        return None

    def fake_vector_store_connect():
        return None

    async def fake_vector_store_ensure_ready():
        return None

    def fake_vector_store_disconnect():
        return None

    def fake_connect():
        return None

    def fake_disconnect():
        return None

    def fake_build_graph():
        return None

    monkeypatch.setattr(main_module.settings, 'ENVIRONMENT', 'production')
    monkeypatch.setattr(main_module.settings, 'AUTH_ENABLED', False)
    monkeypatch.setattr(main_module.settings, 'AUTH_ALLOW_ANONYMOUS', True)
    monkeypatch.setattr(main_module.postgres_manager, 'init_db', fake_init_db)
    monkeypatch.setattr(main_module, 'recover_wiki_compile_jobs', fake_recover_wiki_compile_jobs)
    monkeypatch.setattr(main_module.postgres_manager, 'close_db', fake_close_db)
    monkeypatch.setattr(main_module.vector_store, 'connect', fake_vector_store_connect)
    monkeypatch.setattr(main_module.vector_store, 'ensure_ready', fake_vector_store_ensure_ready)
    monkeypatch.setattr(main_module.vector_store, 'disconnect', fake_vector_store_disconnect)
    monkeypatch.setattr(main_module.llm_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.llm_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.embedding_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.embedding_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.reranker_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.reranker_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.agentic_rag_manager, 'build_graph', fake_build_graph)

    with TestClient(main_module.app) as client:
        response = client.get('/')

    assert response.status_code == 200
    assert events == ['postgres.init_db']


def test_app_startup_allows_production_with_trusted_oidc(monkeypatch):
    events = []

    async def fake_init_db():
        events.append('postgres.init_db')

    async def fake_recover_wiki_compile_jobs(submit_job):
        return {'recovered_count': 0, 'job_ids': []}

    async def fake_close_db():
        return None

    def fake_vector_store_connect():
        return None

    async def fake_vector_store_ensure_ready():
        return None

    def fake_vector_store_disconnect():
        return None

    def fake_connect():
        return None

    def fake_disconnect():
        return None

    def fake_build_graph():
        return None

    monkeypatch.setattr(main_module.settings, 'ENVIRONMENT', 'production')
    monkeypatch.setattr(main_module.settings, 'AUTH_ENABLED', False)
    monkeypatch.setattr(main_module.settings, 'AUTH_ALLOW_ANONYMOUS', False)
    monkeypatch.setattr(main_module.settings, 'OIDC_TRUSTED_HEADER_ENABLED', True)
    monkeypatch.setattr(main_module.postgres_manager, 'init_db', fake_init_db)
    monkeypatch.setattr(main_module, 'recover_wiki_compile_jobs', fake_recover_wiki_compile_jobs)
    monkeypatch.setattr(main_module.postgres_manager, 'close_db', fake_close_db)
    monkeypatch.setattr(main_module.vector_store, 'connect', fake_vector_store_connect)
    monkeypatch.setattr(main_module.vector_store, 'ensure_ready', fake_vector_store_ensure_ready)
    monkeypatch.setattr(main_module.vector_store, 'disconnect', fake_vector_store_disconnect)
    monkeypatch.setattr(main_module.llm_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.llm_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.embedding_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.embedding_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.reranker_manager, 'connect', fake_connect)
    monkeypatch.setattr(main_module.reranker_manager, 'disconnect', fake_disconnect)
    monkeypatch.setattr(main_module.agentic_rag_manager, 'build_graph', fake_build_graph)

    with TestClient(main_module.app) as client:
        response = client.get('/')

    assert response.status_code == 200
    assert events == ['postgres.init_db']
