import pytest
from langchain_core.messages import AIMessage

from app.agents.nodes import (
    _detect_direct_reply_query,
    _parse_quality_score,
    answer_generator,
    context_builder,
    decision_maker,
    quality_evaluator,
    query_analyzer,
    reranker,
    retriever,
)
from app.services.retrieval import RetrievalProviderResult, RetrievalResponse


class DummyEmbeddingManager:
    async def create_embedding(self, user_query):
        return [0.1, 0.2, 0.3]


class DummyAsyncSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class DummyLLMManager:
    def __init__(self, content: str):
        self.content = content

    async def chat_completion(self, **kwargs):
        return {"choices": [{"message": {"content": self.content}}]}


class SequencedLLMManager:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def make_state(**overrides):
    state = {
        "messages": [],
        "tenant_id": "default",
        "user_query": "什么是测试？",
        "query_analysis": {"top_k": 3, "needs_rerank": True},
        "search_results": None,
        "reranked_results": None,
        "context": None,
        "answer": "测试答案",
        "quality_score": None,
        "retrieval_count": 0,
        "max_retrievals": 2,
        "should_continue": True,
        "error": None,
    }
    state.update(overrides)
    return state


def test_parse_quality_score_supports_plain_number_and_embedded_number():
    assert _parse_quality_score("0.82") == 0.82
    assert _parse_quality_score("评分: 0.73") == 0.73
    assert _parse_quality_score("85%") == 0.85
    assert _parse_quality_score("85 分") == 0.85
    assert _parse_quality_score("") is None
    assert _parse_quality_score("没有分数") is None


def test_detect_direct_reply_query_for_greeting():
    analysis = _detect_direct_reply_query("你好")

    assert analysis is not None
    assert analysis["query_type"] == "greeting"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("history_messages", "user_query", "standalone_query", "expected_entity"),
    [
        (
            [
                {"role": "system", "content": "以下是当前会话的历史摘要：用户正在询问请假制度。"},
                {"role": "user", "content": "请假制度怎么规定？"},
                {"role": "assistant", "content": "请假制度规定员工应提前提交申请。"},
            ],
            "那它适用于实习生吗？",
            "请假制度是否适用于实习生？",
            "请假制度",
        ),
        (
            [
                {"role": "user", "content": "差旅报销标准是什么？"},
                {"role": "assistant", "content": "差旅报销包括交通、住宿和餐补标准。"},
            ],
            "需要哪些票据？",
            "差旅报销需要哪些票据？",
            "差旅报销",
        ),
        (
            [
                {"role": "user", "content": "请列出请假制度的前三条。"},
                {"role": "assistant", "content": "1. 年假提前申请。2. 病假需提交证明。3. 事假需主管审批。"},
            ],
            "第二条呢？",
            "请假制度第二条病假需提交证明的具体要求是什么？",
            "请假制度",
        ),
    ],
)
async def test_query_analyzer_rewrites_followup_with_conversation_context(monkeypatch, history_messages, user_query, standalone_query, expected_entity):
    llm = SequencedLLMManager([
        {
            "choices": [{
                "message": {
                    "content": (
                        '{"standalone_query": "' + standalone_query + '", '
                        '"query_type": "factual", "complexity": "medium", '
                        '"keywords": ["' + expected_entity + '"], "search_scope": "medium", '
                        '"top_k": 3, "needs_rerank": false, "route": "hybrid", '
                        '"sub_queries": ["' + standalone_query + '"], "filters": {}, '
                        '"top_k_dense": 3, "top_k_sparse": 3, "rerank_top_n": 3, '
                        '"answer_style": "detailed", "hops": [], "explanation": "follow-up rewrite"}'
                    )
                }
            }]
        }
    ])
    monkeypatch.setattr("app.agents.nodes.llm_manager", llm)
    state = make_state(
        user_query=user_query,
        messages=[
            *history_messages,
            {"role": "user", "content": user_query},
        ],
    )

    result = await query_analyzer(state)

    assert result["standalone_query"] == standalone_query
    assert result["current_query"] == standalone_query
    assert expected_entity in result["current_query"]
    assert "对话上下文" in llm.calls[0]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_query_analyzer_reuses_cached_analysis(monkeypatch):
    llm = SequencedLLMManager([
        {
            "choices": [{
                "message": {
                    "content": (
                        '{"standalone_query": "请假制度适用范围是什么？", '
                        '"query_type": "factual", "complexity": "medium", '
                        '"keywords": ["请假制度"], "search_scope": "medium", '
                        '"top_k": 3, "needs_rerank": false, "route": "hybrid", '
                        '"sub_queries": ["请假制度适用范围是什么？"], "filters": {}, '
                        '"top_k_dense": 3, "top_k_sparse": 3, "rerank_top_n": 3, '
                        '"answer_style": "detailed", "hops": [], "explanation": "cached"}'
                    )
                }
            }]
        }
    ])
    monkeypatch.setattr("app.agents.nodes.llm_manager", llm)

    first = await query_analyzer(make_state(user_query="请假制度适用范围是什么？"))
    second = await query_analyzer(make_state(user_query="请假制度适用范围是什么？"))

    assert first["standalone_query"] == second["standalone_query"]
    assert len(llm.calls) == 1
    assert "命中缓存" in second["messages"][-1].content


@pytest.mark.asyncio
async def test_query_analyzer_short_circuits_greeting():
    state = make_state(user_query="你好")

    result = await query_analyzer(state)

    assert result["query_analysis"]["query_type"] == "greeting"
    assert result["messages"][-1].content == "查询识别为 greeting，直接回答"


@pytest.mark.asyncio
async def test_retriever_increments_count_even_when_no_results(monkeypatch):
    state = make_state()

    monkeypatch.setattr("app.services.retrieval.embedding_manager", DummyEmbeddingManager())
    async def fake_search_vectors(query_vectors, top_k, tenant_id=None, **kwargs):
        return [[]]

    monkeypatch.setattr("app.services.retrieval.vector_store.search_vectors", fake_search_vectors)
    async def fake_sparse_search_chunks(query, tenant_id=None, top_k=10):
        return []

    monkeypatch.setattr("app.services.retrieval.sparse_search_chunks", fake_sparse_search_chunks)
    monkeypatch.setattr("app.services.retrieval.async_session_maker", lambda: DummyAsyncSession())
    async def fake_search_wiki_pages(session, tenant_id, query, knowledge_base=None, top_k=5):
        return []

    monkeypatch.setattr("app.services.retrieval.search_wiki_pages", fake_search_wiki_pages)

    result = await retriever(state)

    assert result["retrieval_count"] == 1
    assert result["search_results"] == []
    assert result["reranked_results"] == []
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content == "未找到相关文档"


@pytest.mark.asyncio
async def test_retriever_counts_failed_attempt_when_search_raises(monkeypatch):
    state = make_state()

    monkeypatch.setattr("app.services.retrieval.embedding_manager", DummyEmbeddingManager())
    async def raise_search_error(*args, **kwargs):
        raise RuntimeError("milvus temporarily unavailable")

    monkeypatch.setattr("app.services.retrieval.vector_store.search_vectors", raise_search_error)
    async def fake_sparse_search_chunks(query, tenant_id=None, top_k=10):
        return []

    monkeypatch.setattr("app.services.retrieval.sparse_search_chunks", fake_sparse_search_chunks)
    monkeypatch.setattr("app.services.retrieval.async_session_maker", lambda: DummyAsyncSession())
    async def fake_search_wiki_pages(session, tenant_id, query, knowledge_base=None, top_k=5):
        return []

    monkeypatch.setattr("app.services.retrieval.search_wiki_pages", fake_search_wiki_pages)

    result = await retriever(state)

    assert result["retrieval_count"] == 1
    assert result["search_results"] == []
    assert result["error"] == "milvus temporarily unavailable"


@pytest.mark.asyncio
async def test_retriever_skips_vector_search_for_direct_reply(monkeypatch):
    state = make_state(query_analysis={"query_type": "greeting", "top_k": 0, "needs_rerank": False})

    async def should_not_run(*args, **kwargs):
        raise AssertionError("vector search should not run")

    monkeypatch.setattr("app.services.retrieval.vector_store.search_vectors", should_not_run)

    result = await retriever(state)

    assert result["retrieval_count"] == 0
    assert result["search_results"] == []
    assert result["messages"][-1].content == "当前查询无需知识库检索，直接回答"


@pytest.mark.asyncio
async def test_retriever_merges_wiki_hits(monkeypatch):
    state = make_state(
        query_analysis={"top_k": 3, "needs_rerank": False, "route": "hybrid"},
        query_plan={"route": "hybrid", "top_k_dense": 3, "top_k_sparse": 3, "filters": {}},
    )

    monkeypatch.setattr("app.services.retrieval.embedding_manager", DummyEmbeddingManager())

    async def fake_search_vectors(query_vectors, top_k, tenant_id=None, **kwargs):
        return [[{
            "id": 11,
            "distance": 0.12,
            "score": 0.88,
            "metadata": {
                "document_id": 1,
                "chunk_id": 11,
                "document_title": "原始制度文档",
                "text": "原始 chunk 内容",
            },
        }]]

    async def fake_hydrate_vector_hits(hits, tenant_id=None):
        return hits

    async def fake_sparse_search_chunks(query, tenant_id=None, top_k=10):
        return []

    async def fake_search_wiki_pages(session, tenant_id, query, knowledge_base=None, top_k=5):
        return [{
            "id": "wiki:3",
            "wiki_page_id": 3,
            "document_id": None,
            "chunk_id": None,
            "document_title": "请假制度 Wiki",
            "title": "请假制度 Wiki",
            "text": "Wiki 汇总页内容",
            "content": "Wiki 汇总页内容",
            "metadata": {
                "source_type": "wiki_page",
                "wiki_page_id": 3,
                "wiki_slug": "leave-policy",
            },
            "score": 2.0,
        }]

    monkeypatch.setattr("app.services.retrieval.vector_store.search_vectors", fake_search_vectors)
    monkeypatch.setattr("app.services.retrieval.hydrate_vector_hits", fake_hydrate_vector_hits)
    monkeypatch.setattr("app.services.retrieval.sparse_search_chunks", fake_sparse_search_chunks)
    monkeypatch.setattr("app.services.retrieval.async_session_maker", lambda: DummyAsyncSession())
    monkeypatch.setattr("app.services.retrieval.search_wiki_pages", fake_search_wiki_pages)

    result = await retriever(state)

    assert result["retrieval_count"] == 1
    assert len(result["search_results"]) >= 1
    assert any(item.get("wiki_page_id") == 3 or (item.get("metadata") or {}).get("wiki_page_id") == 3 for item in result["search_results"])


@pytest.mark.asyncio
async def test_retriever_passes_capped_sub_queries_to_orchestrator(monkeypatch):
    class FakeOrchestrator:
        def __init__(self):
            self.queries = None
            self.request = None

        async def retrieve_many(self, request, queries):
            self.request = request
            self.queries = queries
            return RetrievalResponse(
                documents=[{"id": "doc:1", "chunk_id": 1, "text": "命中内容"}],
                provider_results={
                    "vector": RetrievalProviderResult("vector", hits=[{"id": "doc:1"}]),
                    "sparse": RetrievalProviderResult("sparse", hits=[]),
                    "wiki": RetrievalProviderResult("wiki", hits=[]),
                },
                queries=queries,
            )

    fake_orchestrator = FakeOrchestrator()
    monkeypatch.setattr("app.agents.nodes.default_retrieval_orchestrator", fake_orchestrator)

    state = make_state(
        current_query="问题一",
        query_analysis={
            "top_k": 3,
            "needs_rerank": False,
            "route": "hybrid",
            "sub_queries": ["问题一", "问题二", "问题三", "问题四"],
        },
        query_plan={
            "route": "hybrid",
            "top_k_dense": 3,
            "top_k_sparse": 3,
            "filters": {"knowledge_base": "hr"},
            "sub_queries": ["问题一", "问题二", "问题三", "问题四"],
        },
    )

    result = await retriever(state)

    assert fake_orchestrator.queries == ["问题一", "问题二", "问题三"]
    assert fake_orchestrator.request.filters == {"knowledge_base": "hr"}
    assert result["query_rewrites"] == ["问题一", "问题二", "问题三"]
    assert result["retrieval_attempts"][0]["query_count"] == 3


@pytest.mark.asyncio
async def test_retriever_treats_provider_error_as_degraded_when_documents_exist(monkeypatch):
    class FakeOrchestrator:
        async def retrieve_many(self, request, queries):
            return RetrievalResponse(
                documents=[{"id": "doc:1", "chunk_id": 1, "text": "可用结果"}],
                provider_results={
                    "vector": RetrievalProviderResult("vector", hits=[{"id": "doc:1"}]),
                    "sparse": RetrievalProviderResult("sparse", error="sparse timeout"),
                    "wiki": RetrievalProviderResult("wiki", hits=[]),
                },
                queries=queries,
            )

    monkeypatch.setattr("app.agents.nodes.default_retrieval_orchestrator", FakeOrchestrator())

    result = await retriever(make_state())

    assert result["search_results"] == [{"id": "doc:1", "chunk_id": 1, "text": "可用结果"}]
    assert result["retrieval_error"] is None
    assert result["error"] is None
    assert result["retrieval_attempts"][0]["degraded"] is True
    assert result["retrieval_attempts"][0]["sparse_error"] == "sparse timeout"


@pytest.mark.asyncio
async def test_context_builder_skips_context_for_direct_reply():
    state = make_state(query_analysis={"query_type": "greeting"})

    result = await context_builder(state)

    assert result["context"] == ""
    assert result["messages"][-1].content == "上下文构建完成（直接回答模式）"


@pytest.mark.asyncio
async def test_answer_generator_returns_natural_reply_for_greeting(monkeypatch):
    state = make_state(query_analysis={"query_type": "greeting"}, user_query="你好")
    monkeypatch.setattr("app.agents.nodes.llm_manager", DummyLLMManager("你好，很高兴为你服务！"))

    result = await answer_generator(state)

    assert result["answer"] == "你好，很高兴为你服务！"


@pytest.mark.asyncio
async def test_quality_evaluator_skips_for_direct_reply():
    state = make_state(query_analysis={"query_type": "greeting"})

    result = await quality_evaluator(state)

    assert result["quality_score"] == 1.0
    assert result["messages"][-1].content == "直接回答模式，跳过质量评估"


@pytest.mark.asyncio
async def test_quality_evaluator_skips_model_call_when_no_documents(monkeypatch):
    state = make_state(search_results=[], reranked_results=[])

    async def should_not_run(**kwargs):
        raise AssertionError("quality model should not be called")

    monkeypatch.setattr("app.agents.nodes.llm_manager.chat_completion", should_not_run)

    result = await quality_evaluator(state)

    assert result["quality_score"] == 0.0
    assert result["messages"][-1].content == "未检索到文档，跳过质量评估"


@pytest.mark.asyncio
async def test_quality_evaluator_parses_score_with_extra_text(monkeypatch):
    state = make_state(search_results=[{"text": "doc"}], reranked_results=[{"text": "doc"}])
    monkeypatch.setattr("app.agents.nodes.llm_manager", DummyLLMManager("最终评分：0.67"))

    result = await quality_evaluator(state)

    assert result["quality_score"] == 0.67
    assert result["quality_evaluation"]["groundedness"] == 0.67


@pytest.mark.asyncio
async def test_quality_evaluator_uses_context_and_parses_structured_scores(monkeypatch):
    state = make_state(
        user_query="请假制度适用范围是什么？",
        answer="请假制度适用于正式员工。",
        context="请假制度适用于正式员工和实习生。",
        citations=[{"claim": "请假制度适用范围"}],
        search_results=[{"text": "doc"}],
        reranked_results=[{"text": "doc"}],
    )
    captured = {}

    class CapturingLLM:
        async def chat_completion(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return {
                "choices": [{
                    "message": {
                        "content": '{"groundedness":0.8,"relevance":0.9,"quality_score":0.85,"missing_information":["实习生"],"reason":"答案漏掉实习生"}'
                    },
                    "finish_reason": "stop",
                }]
            }

    monkeypatch.setattr("app.agents.nodes.llm_manager", CapturingLLM())

    result = await quality_evaluator(state)

    prompt = captured["messages"][1]["content"]
    assert "检索上下文" in prompt
    assert "请假制度适用于正式员工和实习生" in prompt
    assert result["quality_score"] == 0.85
    assert result["quality_evaluation"]["groundedness"] == 0.8
    assert result["quality_evaluation"]["relevance"] == 0.9
    assert result["quality_evaluation"]["missing_information"] == ["实习生"]


@pytest.mark.asyncio
async def test_quality_evaluator_retries_when_qwen_returns_empty_length(monkeypatch):
    state = make_state(search_results=[{"text": "doc"}], reranked_results=[{"text": "doc"}])
    llm = SequencedLLMManager([
        {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "0.88"}, "finish_reason": "stop"}]},
    ])
    monkeypatch.setattr("app.agents.nodes.llm_manager", llm)

    result = await quality_evaluator(state)

    assert result["quality_score"] == 0.88
    assert len(llm.calls) == 2
    assert llm.calls[0]["max_tokens"] == 128
    assert llm.calls[1]["max_tokens"] == 512


@pytest.mark.asyncio
async def test_quality_evaluator_marks_failure_without_silent_mid_score(monkeypatch):
    state = make_state(search_results=[{"text": "doc"}], reranked_results=[{"text": "doc"}])

    class FailingLLM:
        async def chat_completion(self, **kwargs):
            raise RuntimeError("judge unavailable")

    monkeypatch.setattr("app.agents.nodes.llm_manager", FailingLLM())

    result = await quality_evaluator(state)

    assert result["quality_score"] is None
    assert result["quality_evaluation_status"] == "failed"
    assert result["quality_evaluation"]["reason"] == "quality_evaluation_failed: judge unavailable"
    assert result["uncertainty"]["label"] == "未完成质检"


def test_decision_maker_ends_when_no_documents_found():
    state = make_state(search_results=[], reranked_results=[], retrieval_count=1, quality_score=0.5)

    decision = decision_maker(state)

    assert decision == "end"
    assert state["should_continue"] is False


def test_decision_maker_adapts_query_before_quality_retry():
    state = make_state(
        user_query="那它适用于实习生吗？",
        standalone_query="请假制度是否适用于实习生？",
        current_query="请假制度是否适用于实习生？",
        query_analysis={
            "query_type": "factual",
            "keywords": ["请假制度"],
            "route": "vector",
            "top_k": 4,
            "top_k_dense": 4,
            "top_k_sparse": 0,
            "sub_queries": ["请假制度是否适用于实习生？"],
            "needs_rerank": False,
        },
        query_plan={
            "route": "vector",
            "top_k_dense": 4,
            "top_k_sparse": 0,
            "sub_queries": ["请假制度是否适用于实习生？"],
            "hops": [{"hop": 1}],
        },
        search_results=[{"text": "doc"}],
        reranked_results=[{"text": "doc"}],
        retrieval_count=1,
        max_retrievals=2,
        quality_score=0.4,
        quality_evaluation={"missing_information": ["实习生适用范围"]},
    )

    decision = decision_maker(state)

    assert decision == "continue"
    assert state["should_continue"] is True
    assert state["query_analysis"]["route"] == "hybrid"
    assert state["query_analysis"]["needs_rerank"] is True
    assert "实习生适用范围" in state["current_query"]
    assert state["query_plan"]["top_k_dense"] > 4
    assert state["query_plan"]["top_k_sparse"] > 0
    assert state["query_plan"]["hops"] == []
    assert "自适应重检索" in state["retrieval_feedback"]


def test_decision_maker_ends_when_quality_evaluation_failed():
    state = make_state(
        search_results=[{"text": "doc"}],
        reranked_results=[{"text": "doc"}],
        retrieval_count=1,
        max_retrievals=2,
        quality_score=None,
        quality_evaluation_status="failed",
    )

    decision = decision_maker(state)

    assert decision == "end"
    assert state["should_continue"] is False


def test_decision_maker_retries_when_retrieval_failed_and_budget_remains():
    state = make_state(
        search_results=[],
        reranked_results=[],
        retrieval_count=1,
        max_retrievals=2,
        quality_score=0.0,
        error="milvus timeout",
    )

    decision = decision_maker(state)

    assert decision == "continue"
    assert state["should_continue"] is True


def test_decision_maker_ends_when_retrieval_failed_and_budget_exhausted():
    state = make_state(
        search_results=[],
        reranked_results=[],
        retrieval_count=2,
        max_retrievals=2,
        quality_score=0.0,
        error="milvus timeout",
    )

    decision = decision_maker(state)

    assert decision == "end"
    assert state["should_continue"] is False


def test_decision_maker_ends_for_direct_reply():
    state = make_state(query_analysis={"query_type": "greeting"}, quality_score=1.0)

    decision = decision_maker(state)

    assert decision == "end"
    assert state["should_continue"] is False



def test_decision_maker_ends_when_answer_generation_failed():
    state = make_state(
        search_results=[{"text": "doc"}],
        reranked_results=[{"text": "doc"}],
        retrieval_count=1,
        max_retrievals=2,
        quality_score=0.0,
        answer_error="llm failed",
        error="llm failed",
    )

    decision = decision_maker(state)

    assert decision == "end"
    assert state["should_continue"] is False


@pytest.mark.asyncio
async def test_context_builder_trims_retrieval_results(monkeypatch):
    long_text = 'A' * 2000
    state = make_state(
        reranked_results=[
            {'text': long_text},
            {'text': long_text},
            {'text': long_text},
            {'text': long_text},
            {'text': long_text},
        ],
        search_results=[],
    )

    async def fake_count_tokens(text):
        return max(1, len(text) // 100)

    monkeypatch.setattr('app.context.assembler.llm_manager.count_tokens', fake_count_tokens)

    result = await context_builder(state)

    assert result['context_status']['retrieval_doc_count'] <= 4
    assert result['context_status']['retrieval_token_budget'] == 4096
    assert len(result['context']) > 0


@pytest.mark.asyncio
async def test_context_builder_builds_citations_and_evidence(monkeypatch):
    state = make_state(
        reranked_results=[
            {
                'document_id': 1,
                'chunk_id': 11,
                'document_title': '制度A',
                'text': '第一段证据。第二段证据。',
                'page_number': 2,
                'chunk_index': 3,
                'created_at': '2026-06-14T10:00:00',
                'metadata': {'paragraph_index': 5},
            }
        ]
    )

    async def fake_count_tokens(text):
        return 10

    monkeypatch.setattr('app.context.assembler.llm_manager.count_tokens', fake_count_tokens)

    result = await context_builder(state)

    assert result['citations'][0]['sources'][0]['title'] == '制度A'
    assert result['citations'][0]['sources'][0]['page'] == 2
    assert result['evidence_cards'][0]['highlighted_sentences']
    assert result['context_status']['citations_count'] == 1


@pytest.mark.asyncio
async def test_quality_evaluator_builds_uncertainty_and_refusal_when_no_docs():
    state = make_state(search_results=[], reranked_results=[])

    result = await quality_evaluator(state)

    assert result['quality_score'] == 0.0
    assert result['uncertainty']['label'] == '未找到可靠依据'
    assert result['refusal']['should_refuse'] is True


@pytest.mark.asyncio
async def test_answer_generator_refuses_when_no_results():
    state = make_state(search_results=[], reranked_results=[], context='没有找到相关的文档信息。')

    result = await answer_generator(state)

    assert result['answer'] == '当前知识库没有足够信息支持这个回答。'
    assert result['refusal']['should_refuse'] is True


def test_decision_maker_ends_when_refusal_ready_and_budget_exhausted():
    state = make_state(
        search_results=[],
        reranked_results=[],
        retrieval_count=2,
        max_retrievals=2,
        quality_score=0.0,
        refusal={'should_refuse': True},
    )

    decision = decision_maker(state)

    assert decision == 'end'
    assert state['should_continue'] is False


def test_split_answer_sentences_and_bind_citations():
    from app.agents.nodes import _bind_answer_citations

    result = _bind_answer_citations(
        '第一句结论【来源1】。第二句补充[2]。第三句说明(来源3)。',
        [{'claim': '结论 1'}, {'claim': '结论 2'}, {'claim': '结论 3'}],
    )

    assert [item['text'] for item in result] == ['第一句结论。', '第二句补充。', '第三句说明。']
    assert result[0]['citation_ids'] == [1]
    assert result[1]['citation_ids'] == [2]
    assert result[2]['citation_ids'] == [3]


def test_bind_answer_citations_uses_global_reference_when_no_markers():
    from app.agents.nodes import _bind_answer_citations

    result = _bind_answer_citations(
        '第一句结论。第二句建议人工确认。',
        [{'claim': '来源 1'}, {'claim': '来源 2'}, {'claim': '来源 3'}, {'claim': '来源 4'}],
    )

    assert result == [{
        'text': '第一句结论。第二句建议人工确认。',
        'citation_ids': [1, 2, 3],
        'citation_scope': 'global',
        'citation_note': '综合参考：来源1-3',
        'uncertainty_flag': True,
    }]


def test_bind_answer_citations_does_not_flag_common_wei_character():
    from app.agents.nodes import _bind_answer_citations

    result = _bind_answer_citations('未命名文档包含制度说明【来源1】。', [{'claim': '来源 1'}])

    assert result[0]['text'] == '未命名文档包含制度说明。'
    assert result[0]['citation_ids'] == [1]
    assert result[0]['uncertainty_flag'] is False


@pytest.mark.asyncio
async def test_answer_generator_outputs_sentence_level_citation_blocks(monkeypatch):
    state = make_state(
        search_results=[{'text': 'doc'}],
        reranked_results=[{'text': 'doc'}],
        citations=[{'claim': '结论 1'}, {'claim': '结论 2'}],
        context='上下文A',
    )
    monkeypatch.setattr('app.agents.nodes.llm_manager', DummyLLMManager('第一句结论【来源1】。第二句补充[2]。'))

    result = await answer_generator(state)

    assert result['answer'] == '第一句结论。\n第二句补充。'
    assert len(result['answer_blocks']) == 2
    assert result['answer_blocks'][0]['citation_ids'] == [1]
    assert result['answer_blocks'][1]['citation_ids'] == [2]


@pytest.mark.asyncio
async def test_answer_generator_includes_table_style_instruction(monkeypatch):
    state = make_state(
        query_plan={'answer_style': 'table'},
        search_results=[{'text': 'doc'}],
        reranked_results=[{'text': 'doc'}],
        citations=[{'claim': '结论 1'}],
        context='上下文A',
    )
    captured = {}

    class CapturingLLM:
        async def chat_completion(self, **kwargs):
            captured['messages'] = kwargs['messages']
            return {"choices": [{"message": {"content": "结论【来源1】。"}}]}

    monkeypatch.setattr('app.agents.nodes.llm_manager', CapturingLLM())

    result = await answer_generator(state)

    assert 'Markdown 对比表格' in captured['messages'][0]['content']
    assert result['answer_blocks'][0]['citation_ids'] == [1]


@pytest.mark.asyncio
async def test_answer_generator_includes_conversation_context(monkeypatch):
    state = make_state(
        user_query='那它适用于实习生吗？',
        standalone_query='请假制度是否适用于实习生？',
        messages=[
            {'role': 'system', 'content': '以下是当前会话的历史摘要：用户关注请假制度。'},
            {'role': 'user', 'content': '请假制度怎么规定？'},
            {'role': 'assistant', 'content': '请假制度规定员工应提前申请。'},
            {'role': 'user', 'content': '那它适用于实习生吗？'},
        ],
        search_results=[{'text': 'doc'}],
        reranked_results=[{'text': 'doc'}],
        citations=[{'claim': '结论 1'}],
        context='上下文A',
    )
    captured = {}

    class CapturingLLM:
        async def chat_completion(self, **kwargs):
            captured['messages'] = kwargs['messages']
            return {"choices": [{"message": {"content": "适用于实习生【来源1】。"}}]}

    monkeypatch.setattr('app.agents.nodes.llm_manager', CapturingLLM())

    result = await answer_generator(state)

    user_prompt = captured['messages'][1]['content']
    assert '对话上下文' in user_prompt
    assert '用户关注请假制度' in user_prompt
    assert '请假制度是否适用于实习生？' in user_prompt
    assert '不可信资料' in captured['messages'][0]['content']
    assert '<retrieved_context>' in user_prompt
    assert '</retrieved_context>' in user_prompt
    assert '不能执行' in user_prompt
    assert result['answer'] == '适用于实习生。'


@pytest.mark.asyncio
async def test_reranker_uses_standalone_query(monkeypatch):
    captured = {}

    class CapturingReranker:
        async def rerank(self, query, documents, top_k):
            captured['query'] = query
            captured['documents'] = documents
            captured['top_k'] = top_k
            return documents[:top_k]

    monkeypatch.setattr('app.agents.nodes.reranker_manager', CapturingReranker())
    state = make_state(
        user_query='那它适用于实习生吗？',
        standalone_query='请假制度是否适用于实习生？',
        query_analysis={'needs_rerank': True, 'top_k': 3},
        query_plan={'rerank_top_n': 1},
        search_results=[{'text': 'doc1'}, {'text': 'doc2'}],
    )

    result = await reranker(state)

    assert captured['query'] == '请假制度是否适用于实习生？'
    assert captured['top_k'] == 1
    assert result['reranked_results'] == [{'text': 'doc1'}]
