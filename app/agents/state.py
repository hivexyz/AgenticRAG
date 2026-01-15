"""
AgenticRAG 状态定义
使用 TypedDict 定义图的状态
"""
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langgraph.graph.message import add_messages


class AgenticRAGState(TypedDict):
    """AgenticRAG 状态类"""
    
    messages: Annotated[list, add_messages]
    user_query: str
    query_analysis: Optional[Dict[str, Any]]
    search_results: Optional[List[Dict[str, Any]]]
    reranked_results: Optional[List[Dict[str, Any]]]
    context: Optional[str]
    answer: Optional[str]
    quality_score: Optional[float]
    retrieval_count: int
    max_retrievals: int
    should_continue: bool
    error: Optional[str]
