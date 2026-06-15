"""Phase 2/3: 上下文治理、会话摘要记忆与增量摘要刷新。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models import llm_manager

RECENT_TURNS = 6
MAX_HISTORY_TOKENS = 2048
SUMMARY_TRIGGER_MESSAGE_COUNT = 12
SUMMARY_KEEP_RECENT_TURNS = 3
SUMMARY_MAX_TOKENS = 512
SUMMARY_PROMPT = """你是会话记忆压缩助手。请将以下历史对话压缩为后续问答可复用的中文摘要。

要求：
1. 保留用户目标、偏好、约束、已确认事实、关键术语、未解决问题
2. 删除寒暄、重复表达、无关赘述
3. 使用简洁条目式中文，控制在 6 条以内
4. 不要编造对话中没有的信息
"""


async def trim_conversation_history(history: List[Dict[str, str]], *, recent_turns: int = RECENT_TURNS, max_tokens: int = MAX_HISTORY_TOKENS) -> List[Dict[str, str]]:
    if not history:
        return []

    max_messages = max(recent_turns * 2, 1)
    trimmed = history[-max_messages:]

    selected: List[Dict[str, str]] = []
    total_tokens = 0
    for item in reversed(trimmed):
        token_count = await llm_manager.count_tokens(item.get("content", ""))
        if selected and total_tokens + token_count > max_tokens:
            break
        if not selected and token_count > max_tokens:
            selected.append(item)
            break
        selected.append(item)
        total_tokens += token_count

    selected.reverse()
    return selected


async def count_history_tokens(history: List[Dict[str, str]]) -> int:
    total = 0
    for item in history:
        total += await llm_manager.count_tokens(item.get("content", ""))
    return total


def build_summary_candidate_messages(
    history: List[Dict[str, str]],
    *,
    keep_recent_turns: int = SUMMARY_KEEP_RECENT_TURNS,
    cutoff_message_id: Optional[int] = None,
) -> List[Dict[str, str]]:
    if not history:
        return []

    eligible = [
        item for item in history
        if cutoff_message_id is None or int(item.get("id") or 0) > cutoff_message_id
    ]
    if not eligible:
        return []

    keep_messages = max(keep_recent_turns * 2, 1)
    if len(eligible) <= keep_messages:
        return []
    return eligible[:-keep_messages]


async def should_refresh_summary(
    history: List[Dict[str, str]],
    *,
    latest_summary: Optional[str] = None,
    cutoff_message_id: Optional[int] = None,
    trigger_message_count: int = SUMMARY_TRIGGER_MESSAGE_COUNT,
    keep_recent_turns: int = SUMMARY_KEEP_RECENT_TURNS,
) -> bool:
    if len(history) < trigger_message_count:
        return False

    candidate_messages = build_summary_candidate_messages(
        history,
        keep_recent_turns=keep_recent_turns,
        cutoff_message_id=cutoff_message_id,
    )
    if len(candidate_messages) < 2:
        return False

    if not latest_summary:
        return True

    latest_scope = max(keep_recent_turns * 2, 1)
    return len(candidate_messages) > latest_scope


def _render_summary_messages(messages: List[Dict[str, str]]) -> str:
    parts = []
    for item in messages:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        if content:
            item_id = item.get("id")
            prefix = f"[{item_id}] " if item_id is not None else ""
            parts.append(f"{prefix}{role}: {content}")
    return "\n".join(parts)


async def generate_session_summary(
    history: List[Dict[str, str]],
    *,
    existing_summary: Optional[str] = None,
    keep_recent_turns: int = SUMMARY_KEEP_RECENT_TURNS,
    max_tokens: int = SUMMARY_MAX_TOKENS,
    cutoff_message_id: Optional[int] = None,
) -> Dict[str, Any]:
    candidate_messages = build_summary_candidate_messages(
        history,
        keep_recent_turns=keep_recent_turns,
        cutoff_message_id=cutoff_message_id,
    )
    if not candidate_messages:
        return {
            "summary": existing_summary,
            "cutoff_message_id": cutoff_message_id,
            "source_message_count": 0,
            "incremental": bool(existing_summary),
        }

    history_block = _render_summary_messages(candidate_messages)
    incremental = bool(existing_summary and cutoff_message_id is not None)
    if existing_summary:
        user_prompt = (
            f"已有历史摘要：\n{existing_summary}\n\n"
            f"请结合以下新增历史消息，输出更新后的完整摘要：\n{history_block}"
        )
    else:
        user_prompt = f"请总结以下历史对话：\n{history_block}"

    response = await llm_manager.chat_completion(
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    summary = response["choices"][0]["message"]["content"].strip()
    new_cutoff = max(int(item.get("id") or 0) for item in candidate_messages) if candidate_messages else cutoff_message_id
    return {
        "summary": summary,
        "cutoff_message_id": new_cutoff,
        "source_message_count": len(candidate_messages),
        "incremental": incremental,
    }


async def compose_history_with_summary(
    history: List[Dict[str, str]],
    *,
    latest_summary: Optional[str] = None,
    recent_turns: int = RECENT_TURNS,
    max_tokens: int = MAX_HISTORY_TOKENS,
) -> Dict[str, Any]:
    trimmed_history = await trim_conversation_history(history, recent_turns=recent_turns, max_tokens=max_tokens)
    composed_history = list(trimmed_history)
    used_summary = False

    if latest_summary:
        composed_history = [
            {
                "role": "system",
                "content": f"以下是当前会话的历史摘要，请在回答时继承这些已确认信息和偏好：\n{latest_summary}",
            },
            *trimmed_history,
        ]
        used_summary = True

    return {
        "history": composed_history,
        "raw_recent_history": trimmed_history,
        "history_message_count": len(trimmed_history),
        "history_token_budget": max_tokens,
        "history_token_count": await count_history_tokens(trimmed_history),
        "recent_turns": recent_turns,
        "summary_present": bool(latest_summary),
        "used_summary": used_summary,
    }


async def build_conversation_context(messages: List[Any], *, latest_summary: Optional[str] = None) -> Dict[str, Any]:
    raw_history = [
        {
            "role": getattr(item, "role", None) or item.get("role"),
            "content": getattr(item, "content", None) or item.get("content", ""),
            "id": getattr(item, "id", None) or item.get("id"),
        }
        for item in messages
    ]
    return await compose_history_with_summary(raw_history, latest_summary=latest_summary)


MAX_RETRIEVAL_DOCS = 4
MAX_RETRIEVAL_TOKENS = 4096
MAX_DOC_CHARS = 800


async def trim_retrieval_results(results: List[Dict[str, Any]], *, max_docs: int = MAX_RETRIEVAL_DOCS, max_tokens: int = MAX_RETRIEVAL_TOKENS, max_doc_chars: int = MAX_DOC_CHARS) -> Dict[str, Any]:
    if not results:
        return {
            "results": [],
            "doc_count": 0,
            "token_budget": max_tokens,
            "max_docs": max_docs,
            "max_doc_chars": max_doc_chars,
        }

    selected = []
    total_tokens = 0
    for item in results[:max_docs]:
        copied = dict(item)
        text = copied.get("text") or copied.get("content") or ""
        trimmed_text = text[:max_doc_chars]
        token_count = await llm_manager.count_tokens(trimmed_text)
        if selected and total_tokens + token_count > max_tokens:
            break
        if not selected and token_count > max_tokens:
            copied["text"] = trimmed_text
            copied["content"] = trimmed_text
            selected.append(copied)
            break
        copied["text"] = trimmed_text
        copied["content"] = trimmed_text
        selected.append(copied)
        total_tokens += token_count

    return {
        "results": selected,
        "doc_count": len(selected),
        "token_budget": max_tokens,
        "max_docs": max_docs,
        "max_doc_chars": max_doc_chars,
    }
