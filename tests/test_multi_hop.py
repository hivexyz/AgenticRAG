import asyncio

import pytest

from app.agents.nodes import _normalize_hops, retriever
from app.services.multi_hop import HopPlan, MultiHopExecutor
from app.services.retrieval import RetrievalProviderResult, RetrievalRequest, RetrievalResponse


class DummyLLM:
    def __init__(self, content='{"文件名": "差旅费管理办法"}', delay=0):
        self.content = content
        self.delay = delay

    async def chat_completion(self, **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return {"choices": [{"message": {"content": self.content}}]}


class RecordingOrchestrator:
    def __init__(self):
        self.calls = []

    async def retrieve_groups(self, request, queries):
        self.calls.append(list(queries))
        groups = []
        for query in queries:
            groups.append((
                f"vector:q{len(self.calls)}",
                [{
                    "id": query,
                    "chunk_id": query,
                    "document_id": 1,
                    "document_title": query,
                    "text": f"{query} 证据",
                }],
            ))
        return groups, {"vector": RetrievalProviderResult("vector", hits=[hit for _, hits in groups for hit in hits])}, queries

    def fuse_groups(self, request, ranked_groups):
        output = []
        seen = set()
        for _, hits in ranked_groups:
            for hit in hits:
                key = hit.get("chunk_id") or hit.get("id")
                if key in seen:
                    continue
                seen.add(key)
                output.append(hit)
        return output[:request.top_k]


def make_request():
    return RetrievalRequest(
        tenant_id="default",
        query="差旅办法里引用的文件，报销标准是什么",
        route="multi_hop",
        top_k=5,
        dense_top_k=5,
        sparse_top_k=5,
        filters={},
    )


def test_normalize_hops_validates_and_truncates(monkeypatch):
    monkeypatch.setattr("app.agents.nodes.settings.MULTI_HOP_MAX_HOPS", 2)
    monkeypatch.setattr("app.agents.nodes.settings.MULTI_HOP_MAX_QUERIES_PER_HOP", 1)
    hops = _normalize_hops({
        "hops": [
            {"hop": 1, "purpose": "找文件", "queries": ["差旅 引用文件", "多余"], "slots": []},
            {
                "hop": 2,
                "purpose": "查标准",
                "depends_on": 1,
                "queries": ["{slots.文件名} 报销标准"],
                "slots": [{"name": "文件名", "instruction": "提取文件名"}],
            },
            {"hop": 3, "purpose": "多余", "queries": ["多余"], "slots": []},
        ]
    })

    assert len(hops) == 2
    assert hops[0]["queries"] == ["差旅 引用文件"]
    assert hops[1]["queries"] == ["{slots.文件名} 报销标准"]


def test_normalize_hops_rejects_invalid_plan():
    assert _normalize_hops({"hops": [{"hop": 2, "queries": ["x"], "slots": []}]}) == []
    assert _normalize_hops({
        "hops": [
            {"hop": 1, "queries": ["x"], "slots": []},
            {"hop": 2, "depends_on": 3, "queries": ["x"], "slots": []},
        ]
    }) == []
    assert _normalize_hops({
        "hops": [
            {
                "hop": 1,
                "queries": ["{slots.文件名} 标准"],
                "slots": [{"name": "另一个槽位", "instruction": "提取"}],
            }
        ]
    }) == []


@pytest.mark.asyncio
async def test_multi_hop_executor_extracts_slot_and_runs_second_hop(monkeypatch):
    orchestrator = RecordingOrchestrator()
    executor = MultiHopExecutor(retrieval_orchestrator=orchestrator)
    monkeypatch.setattr("app.services.multi_hop.llm_manager", DummyLLM())
    async def fake_count_tokens(text):
        return 10

    monkeypatch.setattr("app.context.assembler.llm_manager.count_tokens", fake_count_tokens)

    documents, trace = await executor.execute(
        make_request(),
        [
            HopPlan(hop=1, purpose="找引用文件", queries=["差旅 引用文件"]),
            HopPlan(
                hop=2,
                purpose="查报销标准",
                queries=["{slots.文件名} 报销标准"],
                slots=[{"name": "文件名", "instruction": "提取文件名"}],
                depends_on=1,
            ),
        ],
    )

    assert orchestrator.calls == [["差旅 引用文件"], ["差旅费管理办法 报销标准"]]
    assert documents[0]["document_title"] == "差旅 引用文件"
    assert trace[1].extracted_slots == {"文件名": "差旅费管理办法"}


@pytest.mark.asyncio
async def test_multi_hop_executor_stops_when_slot_missing(monkeypatch):
    orchestrator = RecordingOrchestrator()
    executor = MultiHopExecutor(retrieval_orchestrator=orchestrator)
    monkeypatch.setattr("app.services.multi_hop.llm_manager", DummyLLM('{"文件名": null}'))
    async def fake_count_tokens(text):
        return 10

    monkeypatch.setattr("app.context.assembler.llm_manager.count_tokens", fake_count_tokens)

    documents, trace = await executor.execute(
        make_request(),
        [
            HopPlan(hop=1, purpose="找引用文件", queries=["差旅 引用文件"]),
            HopPlan(
                hop=2,
                purpose="查报销标准",
                queries=["{slots.文件名} 报销标准"],
                slots=[{"name": "文件名", "instruction": "提取文件名"}],
            ),
        ],
    )

    assert orchestrator.calls == [["差旅 引用文件"]]
    assert documents[0]["document_title"] == "差旅 引用文件"
    assert trace[-1].stopped_reason == "slot_not_found"


@pytest.mark.asyncio
async def test_multi_hop_executor_stops_when_slot_llm_times_out(monkeypatch):
    orchestrator = RecordingOrchestrator()
    executor = MultiHopExecutor(retrieval_orchestrator=orchestrator)
    monkeypatch.setattr("app.services.multi_hop.settings.MULTI_HOP_SLOT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("app.services.multi_hop.llm_manager", DummyLLM(delay=1))

    async def fake_count_tokens(text):
        return 10

    monkeypatch.setattr("app.context.assembler.llm_manager.count_tokens", fake_count_tokens)

    documents, trace = await executor.execute(
        make_request(),
        [
            HopPlan(hop=1, purpose="找引用文件", queries=["差旅 引用文件"]),
            HopPlan(
                hop=2,
                purpose="查报销标准",
                queries=["{slots.文件名} 报销标准"],
                slots=[{"name": "文件名", "instruction": "提取文件名"}],
            ),
        ],
    )

    assert orchestrator.calls == [["差旅 引用文件"]]
    assert documents[0]["document_title"] == "差旅 引用文件"
    assert trace[-1].stopped_reason == "slot_not_found"


@pytest.mark.asyncio
async def test_multi_hop_executor_returns_partial_result_on_total_timeout(monkeypatch):
    class SlowSecondHopOrchestrator(RecordingOrchestrator):
        async def retrieve_groups(self, request, queries):
            if self.calls:
                await asyncio.sleep(1)
            return await super().retrieve_groups(request, queries)

    orchestrator = SlowSecondHopOrchestrator()
    executor = MultiHopExecutor(retrieval_orchestrator=orchestrator)
    monkeypatch.setattr("app.services.multi_hop.settings.MULTI_HOP_TOTAL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr("app.services.multi_hop.llm_manager", DummyLLM())

    async def fake_count_tokens(text):
        return 10

    monkeypatch.setattr("app.context.assembler.llm_manager.count_tokens", fake_count_tokens)

    documents, trace = await executor.execute(
        make_request(),
        [
            HopPlan(hop=1, purpose="找引用文件", queries=["差旅 引用文件"]),
            HopPlan(
                hop=2,
                purpose="查报销标准",
                queries=["{slots.文件名} 报销标准"],
                slots=[{"name": "文件名", "instruction": "提取文件名"}],
            ),
        ],
    )

    assert documents[0]["document_title"] == "差旅 引用文件"
    assert trace[-1].stopped_reason == "timeout"


@pytest.mark.asyncio
async def test_retriever_falls_back_when_multi_hop_executor_fails(monkeypatch):
    class FailingExecutor:
        async def execute(self, request, hops):
            raise RuntimeError("multi hop unavailable")

    class FallbackOrchestrator:
        async def retrieve_many(self, request, queries):
            return RetrievalResponse(
                documents=[{"id": "fallback", "chunk_id": 1, "text": "fallback"}],
                provider_results={
                    "vector": RetrievalProviderResult("vector", hits=[{"id": "fallback"}]),
                    "sparse": RetrievalProviderResult("sparse", hits=[]),
                    "wiki": RetrievalProviderResult("wiki", hits=[]),
                },
                queries=queries,
            )

    monkeypatch.setattr("app.agents.nodes.multi_hop_executor", FailingExecutor())
    monkeypatch.setattr("app.agents.nodes.default_retrieval_orchestrator", FallbackOrchestrator())
    state = {
        "messages": [],
        "tenant_id": "default",
        "user_query": "多跳问题",
        "current_query": "多跳问题",
        "query_analysis": {"top_k": 3, "route": "multi_hop"},
        "query_plan": {
            "route": "multi_hop",
            "top_k_dense": 3,
            "top_k_sparse": 3,
            "filters": {},
            "sub_queries": ["多跳问题"],
            "hops": [{"hop": 1, "purpose": "x", "queries": ["x"], "slots": []}],
        },
        "retrieval_attempts": [],
        "retrieval_count": 0,
        "search_results": None,
        "reranked_results": None,
        "error": None,
    }

    result = await retriever(state)

    assert result["search_results"][0]["id"] == "fallback"
    assert result["error"] is None
    assert result["multi_hop_trace"][0]["stopped_reason"] == "fallback"


@pytest.mark.asyncio
async def test_retriever_uses_normal_retrieval_when_multi_hop_disabled(monkeypatch):
    class ShouldNotRunExecutor:
        async def execute(self, request, hops):
            raise AssertionError("multi-hop executor should not run when disabled")

    class FallbackOrchestrator:
        async def retrieve_many(self, request, queries):
            return RetrievalResponse(
                documents=[{"id": "normal", "chunk_id": 1, "text": "normal path"}],
                provider_results={
                    "vector": RetrievalProviderResult("vector", hits=[{"id": "normal"}]),
                    "sparse": RetrievalProviderResult("sparse", hits=[]),
                    "wiki": RetrievalProviderResult("wiki", hits=[]),
                },
                queries=queries,
            )

    monkeypatch.setattr("app.agents.nodes.settings.MULTI_HOP_ENABLED", False)
    monkeypatch.setattr("app.agents.nodes.multi_hop_executor", ShouldNotRunExecutor())
    monkeypatch.setattr("app.agents.nodes.default_retrieval_orchestrator", FallbackOrchestrator())

    result = await retriever({
        "messages": [],
        "tenant_id": "default",
        "user_query": "多跳问题",
        "current_query": "多跳问题",
        "query_analysis": {"top_k": 3, "route": "multi_hop"},
        "query_plan": {
            "route": "multi_hop",
            "top_k_dense": 3,
            "top_k_sparse": 3,
            "filters": {},
            "sub_queries": ["多跳问题"],
            "hops": [{"hop": 1, "purpose": "x", "queries": ["x"], "slots": []}],
        },
        "retrieval_attempts": [],
        "retrieval_count": 0,
        "search_results": None,
        "reranked_results": None,
        "error": None,
    })

    assert result["search_results"][0]["id"] == "normal"
    assert result["multi_hop_trace"] == []
