"""
AgenticRAG 节点实现
定义图中的各个处理节点
"""
from typing import Dict, Any, List
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from app.models import llm_manager, embedding_manager, reranker_manager
from app.database.milvus import milvus_manager
from app.config import settings
from app.utils.logger import logger
from .state import AgenticRAGState


async def query_analyzer(state: AgenticRAGState) -> AgenticRAGState:
    """
    查询分析节点
    分析用户查询，确定检索策略
    """
    logger.info(f"开始分析查询: {state['user_query']}")
    
    try:
        analysis_prompt = f"""分析以下用户查询，提供检索策略建议：

查询: {state['user_query']}

请以 JSON 格式返回分析结果，包含以下字段：
- query_type: 查询类型（factual, conceptual, comparison, how_to, other）
- complexity: 复杂度（low, medium, high）
- keywords: 关键词列表
- search_scope: 搜索范围（narrow, medium, broad）
- top_k: 建议的检索数量（5-20）
- needs_rerank: 是否需要重排序（true/false）
- explanation: 分析说明

只返回 JSON，不要其他内容。"""

        messages = [
            SystemMessage(content="你是一个专业的查询分析助手，擅长分析用户意图并制定检索策略。"),
            HumanMessage(content=analysis_prompt)
        ]
        
        response = await llm_manager.chat_completion(
            messages=[{"role": msg.type, "content": msg.content} for msg in messages],
            temperature=0.3,
            max_tokens=500,
        )
        
        import json
        analysis_text = response["choices"][0]["message"]["content"]
        
        try:
            analysis = json.loads(analysis_text)
        except json.JSONDecodeError:
            logger.warning(f"无法解析查询分析结果，使用默认策略: {analysis_text}")
            analysis = {
                "query_type": "other",
                "complexity": "medium",
                "keywords": [],
                "search_scope": "medium",
                "top_k": 10,
                "needs_rerank": True,
                "explanation": "使用默认策略"
            }
        
        state["query_analysis"] = analysis
        state["messages"].append(AIMessage(content=f"查询分析完成: {analysis['query_type']} - {analysis['complexity']} 复杂度"))
        
        logger.info(f"查询分析完成: {analysis}")
        return state
        
    except Exception as e:
        logger.error(f"查询分析失败: {e}")
        state["query_analysis"] = {
            "query_type": "other",
            "complexity": "medium",
            "keywords": [],
            "search_scope": "medium",
            "top_k": 10,
            "needs_rerank": True,
            "explanation": "分析失败，使用默认策略"
        }
        return state


async def retriever(state: AgenticRAGState) -> AgenticRAGState:
    """
    检索节点
    从 Milvus 向量数据库中检索相关文档
    """
    logger.info(f"开始检索文档，检索次数: {state['retrieval_count'] + 1}")
    
    try:
        if not milvus_manager.connected:
            raise RuntimeError("Milvus 服务未连接")
        
        analysis = state.get("query_analysis", {})
        top_k = analysis.get("top_k", 10)
        
        query_embedding = await embedding_manager.create_embedding(state["user_query"])
        
        search_results = milvus_manager.search_vectors(
            query_vectors=[query_embedding],
            top_k=top_k,
        )
        
        if not search_results or not search_results[0]:
            state["search_results"] = []
            state["messages"].append(AIMessage(content="未找到相关文档"))
            logger.warning("未找到相关文档")
            return state
        
        documents = []
        for hit in search_results[0]:
            doc = hit.get("metadata", {})
            doc["id"] = hit.get("id")
            doc["distance"] = hit.get("distance")
            doc["score"] = hit.get("distance")
            documents.append(doc)
        
        state["search_results"] = documents
        state["retrieval_count"] += 1
        state["messages"].append(AIMessage(content=f"检索到 {len(documents)} 个文档"))
        
        logger.info(f"检索完成，返回 {len(documents)} 个文档")
        return state
        
    except Exception as e:
        logger.error(f"检索失败: {e}")
        state["error"] = str(e)
        state["search_results"] = []
        return state


async def reranker(state: AgenticRAGState) -> AgenticRAGState:
    """
    重排序节点
    使用 Reranker 对检索结果进行重排序
    """
    logger.info("开始重排序文档")
    
    try:
        analysis = state.get("query_analysis", {})
        needs_rerank = analysis.get("needs_rerank", True)
        
        if not needs_rerank:
            state["reranked_results"] = state["search_results"]
            state["messages"].append(AIMessage(content="跳过重排序"))
            return state
        
        if not state["search_results"]:
            state["reranked_results"] = []
            return state
        
        rerank_top_k = min(5, len(state["search_results"]))
        
        reranked_results = await reranker_manager.rerank(
            query=state["user_query"],
            documents=state["search_results"],
            top_k=rerank_top_k,
        )
        
        state["reranked_results"] = reranked_results
        state["messages"].append(AIMessage(content=f"重排序完成，返回 {len(reranked_results)} 个结果"))
        
        logger.info(f"重排序完成，返回 {len(reranked_results)} 个结果")
        return state
        
    except Exception as e:
        logger.error(f"重排序失败: {e}")
        state["reranked_results"] = state["search_results"]
        return state


async def context_builder(state: AgenticRAGState) -> AgenticRAGState:
    """
    上下文构建节点
    将检索结果构建成上下文
    """
    logger.info("开始构建上下文")
    
    try:
        results = state.get("reranked_results") or state.get("search_results", [])
        
        if not results:
            state["context"] = "没有找到相关的文档信息。"
            state["messages"].append(AIMessage(content="上下文构建完成（无结果）"))
            return state
        
        context_parts = []
        for i, doc in enumerate(results[:5], 1):
            text = doc.get("text", doc.get("content", ""))
            if text:
                context_parts.append(f"[文档 {i}] {text}")
        
        context = "\n\n".join(context_parts)
        state["context"] = context
        state["messages"].append(AIMessage(content=f"上下文构建完成，包含 {len(context_parts)} 个文档"))
        
        logger.info(f"上下文构建完成，包含 {len(context_parts)} 个文档")
        return state
        
    except Exception as e:
        logger.error(f"上下文构建失败: {e}")
        state["context"] = ""
        return state


async def answer_generator(state: AgenticRAGState) -> AgenticRAGState:
    """
    答案生成节点
    基于上下文生成答案
    """
    logger.info("开始生成答案")
    
    try:
        system_prompt = """你是一个专业的问答助手。请基于提供的上下文信息回答用户的问题。

回答要求：
1. 只使用提供的上下文信息，不要编造内容
2. 如果上下文中没有相关信息，明确说明
3. 回答要准确、清晰、有条理
4. 可以引用具体的文档内容
5. 使用中文回答"""

        user_prompt = f"""上下文信息：
{state['context']}

用户问题：{state['user_query']}

请基于上下文信息回答用户的问题。"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await llm_manager.chat_completion(
            messages=[{"role": msg.type, "content": msg.content} for msg in messages],
            temperature=0.7,
            max_tokens=1000,
        )
        
        answer = response["choices"][0]["message"]["content"]
        state["answer"] = answer
        state["messages"].append(AIMessage(content=answer))
        
        logger.info(f"答案生成完成，长度: {len(answer)} 字符")
        return state
        
    except Exception as e:
        logger.error(f"答案生成失败: {e}")
        state["error"] = str(e)
        state["answer"] = "抱歉，生成答案时出现错误。"
        return state


async def quality_evaluator(state: AgenticRAGState) -> AgenticRAGState:
    """
    质量评估节点
    评估生成答案的质量
    """
    logger.info("开始评估答案质量")
    
    try:
        evaluation_prompt = f"""请评估以下问答的质量，给出 0 到 1 之间的分数。

用户问题：{state['user_query']}

生成的答案：{state['answer']}

评估标准：
1. 答案是否准确
2. 答案是否完整
3. 答案是否清晰易懂
4. 答案是否直接回答了问题

请只输出分数（0-1 之间的小数），不要输出其他内容。"""

        messages = [
            SystemMessage(content="你是一个专业的问答质量评估助手。"),
            HumanMessage(content=evaluation_prompt)
        ]
        
        response = await llm_manager.chat_completion(
            messages=[{"role": msg.type, "content": msg.content} for msg in messages],
            temperature=0.0,
            max_tokens=10,
        )
        
        score_text = response["choices"][0]["message"]["content"].strip()
        try:
            quality_score = float(score_text)
            quality_score = min(max(quality_score, 0.0), 1.0)
        except ValueError:
            logger.warning(f"无法解析质量分数: {score_text}，使用默认值 0.5")
            quality_score = 0.5
        
        state["quality_score"] = quality_score
        state["messages"].append(AIMessage(content=f"质量评估完成，分数: {quality_score:.2f}"))
        
        logger.info(f"质量评估完成，分数: {quality_score:.2f}")
        return state
        
    except Exception as e:
        logger.error(f"质量评估失败: {e}")
        state["quality_score"] = 0.5
        return state


def decision_maker(state: AgenticRAGState) -> str:
    """
    决策节点
    决定是否继续检索或结束
    """
    quality_threshold = settings.AGENTIC_RAG_QUALITY_THRESHOLD
    quality_score = state.get("quality_score", 0.0)
    retrieval_count = state.get("retrieval_count", 0)
    max_retrievals = state.get("max_retrievals", 2)
    
    if quality_score >= quality_threshold:
        logger.info(f"质量分数 {quality_score:.2f} >= {quality_threshold:.2f}，结束检索")
        state["should_continue"] = False
        return "end"
    
    if retrieval_count >= max_retrievals:
        logger.info(f"已达到最大检索次数 {max_retrievals}，结束检索")
        state["should_continue"] = False
        return "end"
    
    logger.info(f"质量分数 {quality_score:.2f} < 0.8，继续检索（{retrieval_count}/{max_retrievals}）")
    state["should_continue"] = True
    return "continue"
