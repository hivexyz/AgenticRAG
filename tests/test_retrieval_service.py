import asyncio

import pytest

from app.services.retrieval import RetrievalOrchestrator, RetrievalRequest, VectorRetrievalProvider


class StaticProvider:
    def __init__(self, name, hits):
        self.name = name
        self._hits = hits

    async def retrieve(self, request):
        return self._hits


@pytest.mark.asyncio
async def test_retrieval_orchestrator_accepts_custom_provider():
    orchestrator = RetrievalOrchestrator(
        providers=[
            StaticProvider("vector", []),
            StaticProvider("wiki", []),
            StaticProvider(
                "table",
                [{
                    "id": "table:1",
                    "document_id": 7,
                    "chunk_id": "table:1",
                    "document_title": "指标表",
                    "text": "Q4 指标说明",
                    "metadata": {"source_type": "table"},
                }],
            ),
        ]
    )

    response = await orchestrator.retrieve(
        RetrievalRequest(
            tenant_id="default",
            query="Q4 指标",
            route="hybrid",
            top_k=3,
            dense_top_k=3,
            sparse_top_k=0,
            filters={},
        )
    )

    assert response.documents[0]["document_title"] == "指标表"
    attempt = response.attempt_payload(attempt_number=1, query="Q4 指标", route="hybrid")
    assert attempt["table_results"] == 1


@pytest.mark.asyncio
async def test_retrieval_orchestrator_times_out_slow_provider(monkeypatch):
    class SlowProvider:
        name = "slow"

        async def retrieve(self, request):
            await asyncio.sleep(1)
            return [{"id": "slow:1", "text": "too late"}]

    monkeypatch.setattr("app.services.retrieval.settings.RETRIEVAL_PROVIDER_TIMEOUT_SECONDS", 0.01)
    orchestrator = RetrievalOrchestrator(
        providers=[
            StaticProvider("vector", [{"id": "doc:1", "chunk_id": 1, "text": "fast"}]),
            SlowProvider(),
        ]
    )

    response = await orchestrator.retrieve(
        RetrievalRequest(
            tenant_id="default",
            query="制度",
            route="hybrid",
            top_k=3,
            dense_top_k=3,
            sparse_top_k=0,
            filters={},
        )
    )

    assert response.documents[0]["text"] == "fast"
    assert "timed out" in response.provider_results["slow"].error


@pytest.mark.asyncio
async def test_retrieval_orchestrator_uses_capped_unique_queries(monkeypatch):
    class RecordingProvider:
        name = "vector"

        def __init__(self):
            self.queries = []

        async def retrieve(self, request):
            self.queries.append(request.query)
            return [{
                "id": request.query,
                "chunk_id": request.query,
                "document_id": 1,
                "document_title": request.query,
                "text": request.query,
            }]

    provider = RecordingProvider()
    monkeypatch.setattr("app.services.retrieval.settings.AGENTIC_RAG_MAX_SUB_QUERIES", 2)
    orchestrator = RetrievalOrchestrator(providers=[provider])

    response = await orchestrator.retrieve_many(
        RetrievalRequest(
            tenant_id="default",
            query="主问题",
            route="hybrid",
            top_k=5,
            dense_top_k=5,
            sparse_top_k=0,
            filters={},
        ),
        ["主问题", "子问题一", "子问题二"],
    )

    assert provider.queries == ["主问题", "子问题一"]
    assert response.queries == ["主问题", "子问题一"]
    assert {item["document_title"] for item in response.documents} == {"主问题", "子问题一"}


@pytest.mark.asyncio
async def test_retrieval_attempt_payload_reports_raw_and_fused_counts():
    orchestrator = RetrievalOrchestrator(
        providers=[
            StaticProvider("vector", [{"id": 1, "chunk_id": 9, "document_id": 1, "text": "重复命中"}]),
            StaticProvider("wiki", [{"id": "wiki:9", "chunk_id": 9, "document_id": 1, "text": "重复命中"}]),
        ]
    )

    response = await orchestrator.retrieve(
        RetrievalRequest(
            tenant_id="default",
            query="制度",
            route="hybrid",
            top_k=5,
            dense_top_k=5,
            sparse_top_k=0,
            filters={},
        )
    )
    attempt = response.attempt_payload(attempt_number=1, query="制度", route="hybrid")

    assert attempt["raw_results_total"] == 2
    assert attempt["fused_results"] == 1
    assert attempt["merged_results"] == 1


@pytest.mark.asyncio
async def test_vector_provider_executes_supported_filters(monkeypatch):
    class DummyEmbedding:
        async def create_embedding(self, query):
            return [0.1, 0.2]

    class DummyVectorStore:
        backend_name = "milvus"

        def __init__(self):
            self.expr = None

        async def search_vectors(self, query_vectors, top_k=10, expr=None, params=None, tenant_id=None):
            self.expr = expr
            return [[
                {
                    "id": 1,
                    "distance": 0.1,
                    "score": 0.9,
                    "metadata": {
                        "document_id": 7,
                        "chunk_id": 70,
                        "document_title": "HR 制度",
                        "file_type": "txt",
                        "knowledge_base": "hr",
                        "text": "HR 内容",
                    },
                },
                {
                    "id": 2,
                    "distance": 0.2,
                    "score": 0.8,
                    "metadata": {
                        "document_id": 8,
                        "chunk_id": 80,
                        "document_title": "产品制度",
                        "file_type": "txt",
                        "knowledge_base": "product",
                        "text": "产品内容",
                    },
                },
            ]]

    async def passthrough_hydrate(hits, tenant_id=None):
        return hits

    store = DummyVectorStore()
    monkeypatch.setattr("app.services.retrieval.embedding_manager", DummyEmbedding())
    monkeypatch.setattr("app.services.retrieval.vector_store", store)
    monkeypatch.setattr("app.services.retrieval.hydrate_vector_hits", passthrough_hydrate)

    hits = await VectorRetrievalProvider().retrieve(
        RetrievalRequest(
            tenant_id="acme",
            query="请假制度",
            route="hybrid",
            top_k=5,
            dense_top_k=5,
            sparse_top_k=0,
            filters={"knowledge_base": "hr", "document_ids": [7], "file_type": "txt"},
        )
    )

    assert 'metadata["knowledge_base"] == "hr"' in store.expr
    assert 'metadata["document_id"] == 7' in store.expr
    assert [item["document_id"] for item in hits] == [7]
