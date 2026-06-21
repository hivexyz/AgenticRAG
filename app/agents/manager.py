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
        
        messages = []
        
        if conversation_history:
            for msg in conversation_history:
                if msg.get("role") == "system":
                    messages.append(SystemMessage(content=msg["content"]))
                elif msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
        
        messages.append(HumanMessage(content=user_query))
        
        initial_state: AgenticRAGState = {
            "messages": messages,
            "tenant_id": tenant_id,
            "user_query": user_query,
            "current_query": user_query,
            "query_analysis": None,
            "query_plan": None,
            "query_rewrites": [],
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
            "missing_information": [],
            "retrieval_count": 0,
            "max_retrievals": config.get("max_retrievals", self.max_retrievals) if config else self.max_retrievals,
            "should_continue": True,
            "next_action": None,
            "error": None,
            "retrieval_error": None,
            "answer_error": None,
        }
        
        # 确保 config 包含 thread_id（使用 checkpointer 时必需）
        if config is None:
            config = {}
        if "configurable" not in config:
            config["configurable"] = {}
        if "thread_id" not in config["configurable"]:
            import uuid
            config["configurable"]["thread_id"] = str(uuid.uuid4())
        
        try:
            result = await self.graph.ainvoke(initial_state, config)
            
            logger.info(f"AgenticRAG 查询完成，质量分数: {result.get('quality_score', 'N/A')}")
            
            return {
                "query": user_query,
                "answer": result.get("answer"),
                "quality_score": result.get("quality_score"),
                "query_analysis": result.get("query_analysis"),
                "search_results": result.get("search_results"),
                "reranked_results": result.get("reranked_results"),
                "retrieval_count": result.get("retrieval_count"),
                "context": result.get("context"),
                "context_status": result.get("context_status"),
                "citations": result.get("citations"),
                "evidence_cards": result.get("evidence_cards"),
                "answer_blocks": result.get("answer_blocks"),
                "uncertainty": result.get("uncertainty"),
                "refusal": result.get("refusal"),
                "messages": langchain_messages_to_dicts(result.get("messages", [])),
                "error": result.get("error"),
            }
            
        except Exception as e:
            logger.error(f"AgenticRAG 查询失败: {e}")
            return {
                "query": user_query,
                "answer": None,
                "quality_score": None,
                "query_analysis": None,
                "search_results": None,
                "reranked_results": None,
                "retrieval_count": 0,
                "context": None,
                "context_status": None,
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
        
        messages = []
        
        if conversation_history:
            for msg in conversation_history:
                if msg.get("role") == "system":
                    messages.append(SystemMessage(content=msg["content"]))
                elif msg.get("role") == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg.get("role") == "assistant":
                    messages.append(AIMessage(content=msg["content"]))
        
        messages.append(HumanMessage(content=user_query))
        
        initial_state: AgenticRAGState = {
            "messages": messages,
            "tenant_id": tenant_id,
            "user_query": user_query,
            "current_query": user_query,
            "query_analysis": None,
            "query_plan": None,
            "query_rewrites": [],
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
            "missing_information": [],
            "retrieval_count": 0,
            "max_retrievals": config.get("max_retrievals", self.max_retrievals) if config else self.max_retrievals,
            "should_continue": True,
            "next_action": None,
            "error": None,
            "retrieval_error": None,
            "answer_error": None,
        }
        
        # 确保 config 包含 thread_id（使用 checkpointer 时必需）
        if config is None:
            config = {}
        if "configurable" not in config:
            config["configurable"] = {}
        if "thread_id" not in config["configurable"]:
            import uuid
            config["configurable"]["thread_id"] = str(uuid.uuid4())
        
        try:
            async for event in self.graph.astream(initial_state, config):
                yield event
                
        except Exception as e:
            logger.error(f"AgenticRAG 流式查询失败: {e}")
            yield {"error": str(e)}


# 创建全局 AgenticRAG 管理器实例
agentic_rag_manager = AgenticRAGManager()
