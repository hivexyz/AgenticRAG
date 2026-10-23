"""
AgenticRAG 管理器
负责构建和管理 LangGraph 图
"""
from typing import Dict, Any, Optional, List
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from app.config import settings
from app.utils.logger import logger
from app.utils.messages import langchain_messages_to_dicts
from .state import AgenticRAGState
from .nodes import (
    answer_generator_stream,
    query_analyzer,
    retriever,
    reranker,
    context_builder,
    answer_generator,
    quality_evaluator,
    decision_maker,
)


class AgenticRAGManager:
    """AgenticRAG 管理器"""

    def __init__(self):
        self.graph = None
        self.memory = MemorySaver()
        self.max_retrievals = settings.AGENTIC_RAG_MAX_RETRIEVALS
        self.temperature = settings.OPENAI_TEMPERATURE
        self.max_tokens = settings.OPENAI_MAX_TOKENS

    def build_graph(self) -> StateGraph:
        """
        构建 AgenticRAG 图

        Returns:
            构建好的 StateGraph
        """
        logger.info("开始构建 AgenticRAG 图")

        workflow = StateGraph(AgenticRAGState)

        workflow.add_node("query_analyzer", query_analyzer)
        workflow.add_node("retriever", retriever)
        workflow.add_node("reranker", reranker)
        workflow.add_node("context_builder", context_builder)
        workflow.add_node("answer_generator", answer_generator)
        workflow.add_node("quality_evaluator", quality_evaluator)

        workflow.set_entry_point("query_analyzer")

        workflow.add_edge("query_analyzer", "retriever")
        workflow.add_edge("retriever", "reranker")
        workflow.add_edge("reranker", "context_builder")
        workflow.add_edge("context_builder", "answer_generator")
        workflow.add_edge("answer_generator", "quality_evaluator")

        workflow.add_conditional_edges(
            "quality_evaluator",
            decision_maker,
            {
                "continue": "retriever",
                "end": END,
            }
        )

        self.graph = workflow.compile(checkpointer=self.memory)

        logger.info("AgenticRAG 图构建完成")
        return self.graph

    def _build_messages(self, user_query: str, conversation_history: Optional[List[Dict[str, str]]] = None) -> List[Any]:
        messages: List[Any] = []
        if conversation_history:
            for msg in conversation_history:
                if msg.get("role") == "system":
                    messages.append(SystemMessage(content=msg["content"]))
                elif msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
        messages.append(HumanMessage(content=user_query))
        return messages

    def _ensure_thread_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        prepared = dict(config or {})
        prepared.setdefault("configurable", {})
        if "thread_id" not in prepared["configurable"]:
            import uuid
            prepared["configurable"]["thread_id"] = str(uuid.uuid4())
        return prepared

    def _format_result(self, *, user_query: str, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "query": user_query,
            "answer": result.get("answer"),
            "quality_score": result.get("quality_score"),
            "quality_evaluation": result.get("quality_evaluation"),
            "quality_evaluation_status": result.get("quality_evaluation_status"),
            "standalone_query": result.get("standalone_query"),
            "query_rewrites": result.get("query_rewrites"),
            "query_analysis": result.get("query_analysis"),
            "query_plan": result.get("query_plan"),
            "search_results": result.get("search_results"),
            "reranked_results": result.get("reranked_results"),
            "retrieval_count": result.get("retrieval_count"),
            "retrieval_attempts": result.get("retrieval_attempts"),
            "context": result.get("context"),
            "context_status": result.get("context_status"),
            "multi_hop_trace": result.get("multi_hop_trace"),
            "citations": result.get("citations"),
            "evidence_cards": result.get("evidence_cards"),
            "answer_blocks": result.get("answer_blocks"),
            "uncertainty": result.get("uncertainty"),
            "refusal": result.get("refusal"),
            "messages": langchain_messages_to_dicts(result.get("messages", [])),
            "error": result.get("error"),
        }

    def _build_initial_state(
        self,
        *,
        messages: List[Any],
        tenant_id: str,
        user_query: str,
        config: Optional[Dict[str, Any]],
    ) -> AgenticRAGState:
        configured_max_retrievals = (config or {}).get("max_retrievals")
        if configured_max_retrievals is None:
            configured_max_retrievals = self.max_retrievals
        return {
            "messages": messages,
            "tenant_id": tenant_id,
            "user_query": user_query,
            "current_query": user_query,
            "standalone_query": user_query,
            "conversation_context": None,
            "query_analysis": None,
            "query_plan": None,
            "query_rewrites": [],
            "multi_hop_trace": [],
            "retrieval_attempts": [],
            "retrieval_feedback": None,
            "search_results": None,
            "reranked_results": None,
            "context": None,
            "context_status": None,
            "citations": [],
            "evidence_cards": [],
            "answer_blocks": [],
            "uncertainty": None,
            "refusal": None,
            "answer": None,
            "quality_score": None,
            "quality_evaluation": None,
            "quality_evaluation_status": None,
            "retrieval_count": 0,
            "max_retrievals": configured_max_retrievals,
            "should_continue": True,
            "error": None,
            "retrieval_error": None,
            "answer_error": None,
        }

    async def query(
        self,
        user_query: str,
        tenant_id: str = "default",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        执行 AgenticRAG 查询

        Args:
            user_query: 用户查询
            conversation_history: 对话历史
            config: 配置参数

        Returns:
            查询结果
        """
        if not self.graph:
            self.build_graph()

        logger.info(f"执行 AgenticRAG 查询: {user_query}")

        messages = self._build_messages(user_query, conversation_history)

        initial_state = self._build_initial_state(
            messages=messages,
            tenant_id=tenant_id,
            user_query=user_query,
            config=config,
        )

        config = self._ensure_thread_config(config)

        try:
            result = await self.graph.ainvoke(initial_state, config)

            logger.info(f"AgenticRAG 查询完成，质量分数: {result.get('quality_score', 'N/A')}")

            return self._format_result(user_query=user_query, result=result)

        except Exception as e:
            logger.error(f"AgenticRAG 查询失败: {e}")
            return {
                "query": user_query,
                "answer": None,
                "quality_score": None,
                "quality_evaluation": None,
                "quality_evaluation_status": None,
                "standalone_query": None,
                "query_rewrites": [],
                "query_analysis": None,
                "query_plan": None,
                "search_results": None,
                "reranked_results": None,
                "retrieval_count": 0,
                "retrieval_attempts": [],
                "context": None,
                "context_status": None,
                "multi_hop_trace": [],
                "citations": [],
                "evidence_cards": [],
                "answer_blocks": [],
                "uncertainty": None,
                "refusal": None,
                "messages": [],
                "error": str(e),
            }

    async def stream_query(
        self,
        user_query: str,
        tenant_id: str = "default",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        流式执行 AgenticRAG 查询

        Args:
            user_query: 用户查询
            conversation_history: 对话历史
            config: 配置参数

        Yields:
            查询过程中的中间结果
        """
        if not self.graph:
            self.build_graph()

        logger.info(f"流式执行 AgenticRAG 查询: {user_query}")

        messages = self._build_messages(user_query, conversation_history)

        initial_state = self._build_initial_state(
            messages=messages,
            tenant_id=tenant_id,
            user_query=user_query,
            config=config,
        )

        config = self._ensure_thread_config(config)

        try:
            async for event in self.graph.astream(initial_state, config):
                yield event

        except Exception as e:
            logger.error(f"AgenticRAG 流式查询失败: {e}")
            yield {"error": str(e)}

    async def stream_query_response(
        self,
        user_query: str,
        tenant_id: str = "default",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Run the RAG chain with token-level answer events and a final result."""
        logger.info(f"结构化流式执行 AgenticRAG 查询: {user_query}")
        messages = self._build_messages(user_query, conversation_history)
        state = self._build_initial_state(
            messages=messages,
            tenant_id=tenant_id,
            user_query=user_query,
            config=config,
        )

        try:
            yield {"event": "phase", "phase": "query_analyzer", "status": "started"}
            state = await query_analyzer(state)
            yield {
                "event": "phase",
                "phase": "query_analyzer",
                "status": "completed",
                "standalone_query": state.get("standalone_query"),
                "query_analysis": state.get("query_analysis"),
            }

            while True:
                for phase, node in (
                    ("retriever", retriever),
                    ("reranker", reranker),
                    ("context_builder", context_builder),
                ):
                    yield {"event": "phase", "phase": phase, "status": "started"}
                    state = await node(state)
                    yield {
                        "event": "phase",
                        "phase": phase,
                        "status": "completed",
                        "retrieval_count": state.get("retrieval_count"),
                        "retrieval_feedback": state.get("retrieval_feedback"),
                        "multi_hop_trace": state.get("multi_hop_trace"),
                        "context_status": state.get("context_status"),
                    }

                yield {"event": "answer_start"}
                async for delta in answer_generator_stream(state):
                    if delta:
                        yield {"event": "answer_delta", "delta": delta}
                yield {"event": "phase", "phase": "quality_evaluator", "status": "started"}
                state = await quality_evaluator(state)
                if state.get("quality_score") is None or float(state.get("quality_score") or 0.0) < 0.55:
                    yield {
                        "event": "quality_warning",
                        "quality_score": state.get("quality_score"),
                        "quality_evaluation": state.get("quality_evaluation"),
                        "quality_evaluation_status": state.get("quality_evaluation_status"),
                        "uncertainty": state.get("uncertainty"),
                        "refusal": state.get("refusal"),
                    }
                yield {
                    "event": "quality_done",
                    "quality_score": state.get("quality_score"),
                    "quality_evaluation": state.get("quality_evaluation"),
                    "quality_evaluation_status": state.get("quality_evaluation_status"),
                    "uncertainty": state.get("uncertainty"),
                    "refusal": state.get("refusal"),
                }

                decision = decision_maker(state)
                if decision == "continue":
                    yield {
                        "event": "phase",
                        "phase": "retrieval_retry",
                        "status": "started",
                        "retrieval_count": state.get("retrieval_count"),
                        "retrieval_feedback": state.get("retrieval_feedback"),
                    }
                    continue

                yield {
                    "event": "answer_done",
                    "answer": state.get("answer"),
                    "answer_blocks": state.get("answer_blocks"),
                    "citations": state.get("citations"),
                    "evidence_cards": state.get("evidence_cards"),
                    "uncertainty": state.get("uncertainty"),
                    "refusal": state.get("refusal"),
                    "multi_hop_trace": state.get("multi_hop_trace"),
                }
                break

            yield {
                "event": "final",
                "result": self._format_result(user_query=user_query, result=state),
            }
        except Exception as e:
            logger.error(f"结构化流式查询失败: {e}")
            yield {"event": "error", "error": str(e)}


# 创建全局 AgenticRAG 管理器实例
agentic_rag_manager = AgenticRAGManager()
