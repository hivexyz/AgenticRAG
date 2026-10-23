import pytest

from app.agents.manager import AgenticRAGManager


@pytest.mark.asyncio
async def test_stream_query_response_retries_before_answer_done_for_low_quality(monkeypatch):
    async def fake_query_analyzer(state):
        state["query_analysis"] = {
            "query_type": "factual",
            "keywords": ["请假制度"],
            "route": "hybrid",
            "top_k": 3,
            "top_k_dense": 3,
            "top_k_sparse": 3,
            "sub_queries": ["请假制度"],
            "needs_rerank": True,
        }
        state["query_plan"] = {
            "route": "hybrid",
            "top_k_dense": 3,
            "top_k_sparse": 3,
            "sub_queries": ["请假制度"],
            "rerank_top_n": 3,
            "hops": [],
        }
        state["standalone_query"] = "请假制度适用于实习生吗？"
        state["current_query"] = state["standalone_query"]
        return state

    async def fake_retriever(state):
        state["retrieval_count"] += 1
        state["search_results"] = [{"text": "doc"}]
        state["retrieval_feedback"] = f"attempt={state['retrieval_count']}"
        return state

    async def fake_reranker(state):
        state["reranked_results"] = state["search_results"]
        return state

    async def fake_context_builder(state):
        state["context"] = "请假制度适用于实习生。"
        state["citations"] = [{"claim": "请假制度"}]
        return state

    async def fake_answer_generator_stream(state):
        if state["retrieval_count"] == 1:
            state["answer"] = "只适用于正式员工。"
            state["answer_blocks"] = [{"text": "只适用于正式员工。", "citation_ids": [1], "uncertainty_flag": False}]
            yield "只适用于正式员工。"
            return
        state["answer"] = "适用于正式员工和实习生。"
        state["answer_blocks"] = [{"text": "适用于正式员工和实习生。", "citation_ids": [1], "uncertainty_flag": False}]
        yield "适用于正式员工和实习生。"

    async def fake_quality_evaluator(state):
        if state["retrieval_count"] == 1:
            state["quality_score"] = 0.4
            state["quality_evaluation_status"] = "completed"
            state["quality_evaluation"] = {
                "quality_score": 0.4,
                "groundedness": 0.4,
                "relevance": 0.8,
                "missing_information": ["实习生"],
            }
            state["uncertainty"] = {"level": "high", "label": "资料较少"}
            return state
        state["quality_score"] = 0.9
        state["quality_evaluation_status"] = "completed"
        state["quality_evaluation"] = {
            "quality_score": 0.9,
            "groundedness": 0.9,
            "relevance": 0.9,
            "missing_information": [],
        }
        state["uncertainty"] = {"level": "low", "label": "资料充分"}
        return state

    monkeypatch.setattr("app.agents.manager.query_analyzer", fake_query_analyzer)
    monkeypatch.setattr("app.agents.manager.retriever", fake_retriever)
    monkeypatch.setattr("app.agents.manager.reranker", fake_reranker)
    monkeypatch.setattr("app.agents.manager.context_builder", fake_context_builder)
    monkeypatch.setattr("app.agents.manager.answer_generator_stream", fake_answer_generator_stream)
    monkeypatch.setattr("app.agents.manager.quality_evaluator", fake_quality_evaluator)

    manager = AgenticRAGManager()
    events = [
        event
        async for event in manager.stream_query_response(
            "那它适用于实习生吗？",
            config={"max_retrievals": 2},
        )
    ]

    event_names = [event["event"] for event in events]
    retry_index = next(index for index, event in enumerate(events) if event.get("phase") == "retrieval_retry")
    first_answer_done_index = event_names.index("answer_done")

    assert retry_index < first_answer_done_index
    assert event_names.count("answer_done") == 1
    assert events[first_answer_done_index]["answer"] == "适用于正式员工和实习生。"
    assert any(event["event"] == "quality_warning" for event in events)
