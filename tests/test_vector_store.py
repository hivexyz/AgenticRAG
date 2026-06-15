import pytest

from app.config import settings
from app.database.vector_store import ConfigurableVectorStore, get_vector_store


class DummyAdapter:
    def __init__(self, name):
        self.backend_name = name
        self.calls = []

    def connect(self):
        self.calls.append(("connect",))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def get_collection_name(self, tenant_id=None):
        self.calls.append(("get_collection_name", tenant_id))
        return f"{self.backend_name}_collection"

    async def ensure_ready(self, **kwargs):
        self.calls.append(("ensure_ready", kwargs))
        return "ok"

    async def insert_vectors(self, vectors, metadata=None, tenant_id=None):
        self.calls.append(("insert_vectors", vectors, metadata, tenant_id))

    async def search_vectors(self, query_vectors, top_k=10, expr=None, params=None, tenant_id=None):
        self.calls.append(("search_vectors", query_vectors, top_k, expr, params, tenant_id))
        return [[{"id": 1, "metadata": {"text": "hello"}, "distance": 0.1, "score": 0.1}]]

    async def delete_vectors_by_document_id(self, document_id, tenant_id=None):
        self.calls.append(("delete_vectors_by_document_id", document_id, tenant_id))
        return 2


def test_get_vector_store_uses_milvus_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "milvus")

    store = get_vector_store()

    assert store.backend_name == "milvus"


def test_get_vector_store_uses_pgvector_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "pgvector")

    store = get_vector_store()

    assert store.backend_name == "pgvector"


@pytest.mark.asyncio
async def test_configurable_vector_store_delegates_to_current_backend(monkeypatch):
    milvus = DummyAdapter("milvus")
    pgvector = DummyAdapter("pgvector")

    import app.database.vector_store as vector_store_module

    monkeypatch.setattr(vector_store_module, "milvus_vector_store", milvus)
    monkeypatch.setattr(vector_store_module, "pgvector_store", pgvector)

    store = ConfigurableVectorStore()

    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "milvus")
    await store.ensure_ready(tenant_id="default")
    await store.insert_vectors([[0.1, 0.2]], [{"document_id": 1}], tenant_id="default")

    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "pgvector")
    results = await store.search_vectors([[0.1, 0.2]], tenant_id="default")
    deleted = await store.delete_vectors_by_document_id(1, tenant_id="default")

    assert milvus.calls[0][0] == "ensure_ready"
    assert milvus.calls[1][0] == "insert_vectors"
    assert pgvector.calls[0][0] == "search_vectors"
    assert pgvector.calls[1][0] == "delete_vectors_by_document_id"
    assert results[0][0]["metadata"]["text"] == "hello"
    assert deleted == 2
