"""
AgenticRAG 状态定义
使用 TypedDict 定义图的状态
"""
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langgraph.graph.message import add_messages


class AgenticRAGState(TypedDict):
    """AgenticRAG 状态类"""

    messages: Annotated[list, add_messages]
    tenant_id: str
    user_query: str
    current_query: str
    standalone_query: Optional[str]
    conversation_context: Optional[str]
    query_analysis: Optional[Dict[str, Any]]
    query_plan: Optional[Dict[str, Any]]
    query_rewrites: List[str]
    multi_hop_trace: Optional[List[Dict[str, Any]]]
    retrieval_attempts: List[Dict[str, Any]]
    retrieval_feedback: Optional[str]
    search_results: Optional[List[Dict[str, Any]]]
    reranked_results: Optional[List[Dict[str, Any]]]
    context: Optional[str]
    context_status: Optional[Dict[str, Any]]
    citations: Optional[List[Dict[str, Any]]]
    evidence_cards: Optional[List[Dict[str, Any]]]
    answer_blocks: Optional[List[Dict[str, Any]]]
    uncertainty: Optional[Dict[str, Any]]
    refusal: Optional[Dict[str, Any]]
    answer: Optional[str]
    quality_score: Optional[float]
    quality_evaluation: Optional[Dict[str, Any]]
    quality_evaluation_status: Optional[str]
    retrieval_count: int
    max_retrievals: int
    should_continue: bool
    error: Optional[str]
    retrieval_error: Optional[str]
    answer_error: Optional[str]
