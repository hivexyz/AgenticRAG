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
    retriever,
)


class DummyEmbeddingManager:
    async def create_embedding(self, user_query):
        return [0.1, 0.2, 0.3]


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
async def test_query_analyzer_short_circuits_greeting():
    state = make_state(user_query="你好")

    result = await query_analyzer(state)

    assert result["query_analysis"]["query_type"] == "greeting"
    assert result["messages"][-1].content == "查询识别为 greeting，直接回答"


@pytest.mark.asyncio
async def test_retriever_increments_count_even_when_no_results(monkeypatch):
    state = make_state()

    monkeypatch.setattr("app.agents.nodes.embedding_manager", DummyEmbeddingManager())
    async def fake_search_vectors(query_vectors, top_k, tenant_id=None):
        return [[]]

    monkeypatch.setattr("app.agents.nodes.vector_store.search_vectors", fake_search_vectors)

    result = await retriever(state)

    assert result["retrieval_count"] == 1
    assert result["search_results"] == []
    assert result["reranked_results"] == []
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content == "未找到相关文档"


@pytest.mark.asyncio
async def test_retriever_counts_failed_attempt_when_search_raises(monkeypatch):
    state = make_state()

    monkeypatch.setattr("app.agents.nodes.embedding_manager", DummyEmbeddingManager())
    async def raise_search_error(*args, **kwargs):
        raise RuntimeError("milvus temporarily unavailable")

    monkeypatch.setattr("app.agents.nodes.vector_store.search_vectors", raise_search_error)

    result = await retriever(state)

    assert result["retrieval_count"] == 1
    assert result["search_results"] == []
    assert result["error"] == "milvus temporarily unavailable"


@pytest.mark.asyncio
async def test_retriever_skips_vector_search_for_direct_reply(monkeypatch):
    state = make_state(query_analysis={"query_type": "greeting", "top_k": 0, "needs_rerank": False})

    async def should_not_run(*args, **kwargs):
        raise AssertionError("vector search should not run")

    monkeypatch.setattr("app.agents.nodes.vector_store.search_vectors", should_not_run)

    result = await retriever(state)

    assert result["retrieval_count"] == 0
    assert result["search_results"] == []
    assert result["messages"][-1].content == "当前查询无需知识库检索，直接回答"


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


def test_decision_maker_ends_when_no_documents_found():
    state = make_state(search_results=[], reranked_results=[], retrieval_count=1, quality_score=0.5)

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
        '第一句结论。【来源1】第二句建议。',
        [{'claim': '结论 1'}, {'claim': '结论 2'}],
    )

    assert len(result) >= 1
    assert result[0]['citation_ids'] == [1]


@pytest.mark.asyncio
async def test_answer_generator_outputs_sentence_level_citation_blocks(monkeypatch):
    state = make_state(
        search_results=[{'text': 'doc'}],
        reranked_results=[{'text': 'doc'}],
        citations=[{'claim': '结论 1'}, {'claim': '结论 2'}],
        context='上下文A',
    )
    monkeypatch.setattr('app.agents.nodes.llm_manager', DummyLLMManager('第一句结论。第二句补充。'))

    result = await answer_generator(state)

    assert len(result['answer_blocks']) == 2
    assert result['answer_blocks'][0]['citation_ids'] == [1]
