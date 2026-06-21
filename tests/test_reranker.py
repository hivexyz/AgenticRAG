import pytest

from app.models.reranker import RerankerManager


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    response_payload = {}
    last_url = None
    last_json = None
    last_headers = None
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, json=None, headers=None):
        FakeAsyncClient.last_url = url
        FakeAsyncClient.last_json = json
        FakeAsyncClient.last_headers = headers
        FakeAsyncClient.calls.append({"url": url, "json": json, "headers": headers})
        return FakeResponse(FakeAsyncClient.response_payload)


def make_connected_manager():
    manager = RerankerManager()
    manager.api_key = "test-key"
    manager.base_url = "http://example.com/v1"
    manager.model = "text-embedding-bge-reranker-v2-m3"
    manager.top_k = 10
    manager.connected = True
    return manager


@pytest.mark.asyncio
async def test_rerank_uses_dedicated_rerank_api(monkeypatch):
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {
        "results": [
            {"index": 1, "relevance_score": 0.91},
            {"index": 0, "relevance_score": 0.23},
        ]
    }
    monkeypatch.setattr("app.models.reranker.httpx.AsyncClient", FakeAsyncClient)

    manager = make_connected_manager()
    documents = [
        {"id": "doc-1", "text": "不相关文档"},
        {"id": "doc-2", "content": "相关文档"},
    ]

    results = await manager.rerank("测试查询", documents, top_k=2)

    assert FakeAsyncClient.last_url == "http://example.com/v1/rerank"
    assert FakeAsyncClient.last_headers["Authorization"] == "Bearer test-key"
    assert FakeAsyncClient.last_json == {
        "model": "text-embedding-bge-reranker-v2-m3",
        "query": "测试查询",
        "documents": ["不相关文档", "相关文档"],
        "top_n": 2,
    }
    assert [item["id"] for item in results] == ["doc-2", "doc-1"]
    assert [item["relevance_score"] for item in results] == [0.91, 0.23]


@pytest.mark.asyncio
async def test_rerank_supports_data_score_response(monkeypatch):
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {
        "data": [
            {"index": 0, "score": "0.4"},
            {"index": 2, "score": "0.95"},
        ]
    }
    monkeypatch.setattr("app.models.reranker.httpx.AsyncClient", FakeAsyncClient)

    manager = make_connected_manager()
    documents = [
        {"id": "doc-1", "text": "文档一"},
        {"id": "doc-2", "text": "文档二"},
        {"id": "doc-3", "text": "文档三"},
    ]

    results = await manager.rerank("测试查询", documents, top_k=1)

    assert [item["id"] for item in results] == ["doc-3"]
    assert results[0]["relevance_score"] == 0.95
    assert FakeAsyncClient.last_json["top_n"] == 1


@pytest.mark.asyncio
async def test_rerank_supports_score_list_response(monkeypatch):
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {"scores": [0.12, "0.97", 0.34]}
    monkeypatch.setattr("app.models.reranker.httpx.AsyncClient", FakeAsyncClient)

    manager = make_connected_manager()
    documents = [
        {"id": "doc-1", "text": "文档一"},
        {"id": "doc-2", "text": "文档二"},
        {"id": "doc-3", "text": "文档三"},
    ]

    results = await manager.rerank("测试查询", documents, top_k=2)

    assert [item["id"] for item in results] == ["doc-2", "doc-3"]
    assert [item["relevance_score"] for item in results] == [0.97, 0.34]


@pytest.mark.asyncio
async def test_rerank_supports_nested_score_list_response(monkeypatch):
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {"results": {"scores": [0.8, 0.1]}}
    monkeypatch.setattr("app.models.reranker.httpx.AsyncClient", FakeAsyncClient)

    manager = make_connected_manager()
    documents = [
        {"id": "doc-1", "text": "文档一"},
        {"id": "doc-2", "text": "文档二"},
    ]

    results = await manager.rerank("测试查询", documents, top_k=2)

    assert [item["id"] for item in results] == ["doc-1", "doc-2"]
    assert [item["relevance_score"] for item in results] == [0.8, 0.1]


@pytest.mark.asyncio
async def test_rerank_keeps_original_order_when_rerank_endpoint_missing(monkeypatch):
    FakeAsyncClient.calls = []
    FakeAsyncClient.response_payload = {"error": "Unexpected endpoint or method. (POST /v1/rerank)"}
    monkeypatch.setattr("app.models.reranker.httpx.AsyncClient", FakeAsyncClient)

    manager = make_connected_manager()
    documents = [
        {"id": "doc-1", "text": "文档一"},
        {"id": "doc-2", "text": "文档二"},
    ]

    results = await manager.rerank("测试查询", documents, top_k=2)

    assert [call["url"] for call in FakeAsyncClient.calls] == ["http://example.com/v1/rerank"]
    assert [item["id"] for item in results] == ["doc-1", "doc-2"]
    assert all("relevance_score" not in item for item in results)


def test_rerank_url_does_not_duplicate_suffix():
    manager = RerankerManager()
    manager.base_url = "http://example.com/v1/rerank"

    assert manager._rerank_url() == "http://example.com/v1/rerank"
