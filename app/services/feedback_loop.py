"""Feedback-driven badcase helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.db_models import AnswerFeedback, ConversationMessage, Document


BADCASE_REASONS = {"not_helpful", "incorrect", "missing_citations", "missing_information"}


def _as_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata(message: Optional[ConversationMessage]) -> Dict[str, Any]:
    value = getattr(message, "message_metadata", None) if message else None
    return value if isinstance(value, dict) else {}


def _feedback_metadata(feedback: AnswerFeedback) -> Dict[str, Any]:
    value = getattr(feedback, "feedback_metadata", None)
    return value if isinstance(value, dict) else {}


def _previous_user_message(
    assistant: Optional[ConversationMessage],
    messages_by_session: Dict[int, List[ConversationMessage]],
) -> Optional[ConversationMessage]:
    if assistant is None or assistant.session_id is None:
        return None
    session_messages = messages_by_session.get(assistant.session_id) or []
    previous_users = [
        item
        for item in session_messages
        if item.role == "user" and item.id is not None and assistant.id is not None and item.id < assistant.id
    ]
    return previous_users[-1] if previous_users else None


def _iter_source_dicts(metadata: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for result in metadata.get("search_results") or []:
        if isinstance(result, dict):
            yield result
    for citation in metadata.get("citations") or []:
        if not isinstance(citation, dict):
            continue
        for source in citation.get("sources") or []:
            if isinstance(source, dict):
                yield source
    for card in metadata.get("evidence_cards") or []:
        if not isinstance(card, dict):
            continue
        source = card.get("source")
        if isinstance(source, dict):
            if card.get("snippet") and not source.get("snippet"):
                source = {**source, "snippet": card.get("snippet")}
            yield source
        view = card.get("view_full_context")
        if isinstance(view, dict):
            yield view


def extract_hit_chunks(*, message_metadata: Dict[str, Any], feedback_metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    seen = set()
    hits: List[Dict[str, Any]] = []
    for source in _iter_source_dicts(message_metadata):
        document_id = _as_int(source.get("document_id"))
        chunk_id = _as_int(source.get("chunk_id") or source.get("id"))
        key = (document_id, chunk_id, source.get("wiki_page_id"))
        if key in seen:
            continue
        seen.add(key)
        hits.append({
            "document_id": document_id,
            "chunk_id": chunk_id,
            "wiki_page_id": _as_int(source.get("wiki_page_id")),
            "title": source.get("document_title") or source.get("title"),
            "source_type": source.get("source_type"),
            "page": source.get("page") or source.get("page_number"),
            "section_title": source.get("section_title"),
            "snippet": (source.get("snippet") or source.get("text") or source.get("content") or "")[:300],
        })

    for document_id in feedback_metadata.get("document_ids") or []:
        parsed_document_id = _as_int(document_id)
        if parsed_document_id is None:
            continue
        key = (parsed_document_id, None, None)
        if key in seen:
            continue
        seen.add(key)
        hits.append({
            "document_id": parsed_document_id,
            "chunk_id": None,
            "wiki_page_id": None,
            "title": None,
            "source_type": "feedback_metadata",
            "page": None,
            "section_title": None,
            "snippet": "",
        })
    return hits


def extract_document_ids(*, hit_chunks: Sequence[Dict[str, Any]]) -> List[int]:
    ids = []
    for hit in hit_chunks:
        document_id = _as_int(hit.get("document_id"))
        if document_id is not None and document_id not in ids:
            ids.append(document_id)
    return ids


def build_golden_candidate(
    *,
    feedback: AnswerFeedback,
    user_message: Optional[ConversationMessage],
    assistant_message: Optional[ConversationMessage],
    hit_chunks: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    assistant_metadata = _metadata(assistant_message)
    answer = feedback.corrected_answer or getattr(assistant_message, "content", "") or ""
    must_hit_chunk_ids = [
        hit["chunk_id"]
        for hit in hit_chunks
        if _as_int(hit.get("chunk_id")) is not None
    ]
    refusal = assistant_metadata.get("refusal") if isinstance(assistant_metadata.get("refusal"), dict) else {}
    return {
        "id": f"feedback_{feedback.id}",
        "question": getattr(user_message, "content", "") or "",
        "must_hit_chunk_ids": list(dict.fromkeys(must_hit_chunk_ids)),
        "reference_answer": answer,
        "must_mention": [feedback.corrected_answer] if feedback.corrected_answer else [],
        "expected_refusal": bool(refusal.get("should_refuse")),
        "source_feedback_id": feedback.id,
        "reason": feedback.reason,
    }


def build_badcase_items(
    feedback_items: Sequence[AnswerFeedback],
    messages: Sequence[ConversationMessage],
    documents: Sequence[Document],
) -> List[Dict[str, Any]]:
    message_by_id = {item.id: item for item in messages}
    messages_by_session: Dict[int, List[ConversationMessage]] = {}
    for message in sorted(messages, key=lambda item: (item.session_id or 0, item.id or 0)):
        messages_by_session.setdefault(message.session_id, []).append(message)
    document_by_id = {item.id: item for item in documents}

    items: List[Dict[str, Any]] = []
    for feedback in sorted(feedback_items, key=lambda item: item.id or 0, reverse=True):
        assistant = message_by_id.get(feedback.message_id)
        user = _previous_user_message(assistant, messages_by_session)
        assistant_metadata = _metadata(assistant)
        feedback_metadata = _feedback_metadata(feedback)
        hit_chunks = extract_hit_chunks(
            message_metadata=assistant_metadata,
            feedback_metadata=feedback_metadata,
        )
        document_ids = extract_document_ids(hit_chunks=hit_chunks)
        documents_payload = [
            document_by_id[document_id].to_dict(include_content=False)
            for document_id in document_ids
            if document_id in document_by_id
        ]
        items.append({
            "feedback": feedback.to_dict(),
            "user_query": getattr(user, "content", None),
            "assistant_answer": getattr(assistant, "content", None),
            "query_plan": assistant_metadata.get("query_plan") or assistant_metadata.get("query_analysis"),
            "query_analysis": assistant_metadata.get("query_analysis"),
            "standalone_query": assistant_metadata.get("standalone_query"),
            "query_rewrites": assistant_metadata.get("query_rewrites") or [],
            "quality_score": assistant_metadata.get("quality_score"),
            "quality_evaluation": assistant_metadata.get("quality_evaluation"),
            "multi_hop_trace": assistant_metadata.get("multi_hop_trace") or [],
            "retrieval_count": assistant_metadata.get("retrieval_count"),
            "retrieval_attempts": assistant_metadata.get("retrieval_attempts") or [],
            "context_status": assistant_metadata.get("context_status"),
            "citations": assistant_metadata.get("citations") or [],
            "answer_blocks": assistant_metadata.get("answer_blocks") or [],
            "evidence_cards": assistant_metadata.get("evidence_cards") or [],
            "hit_chunks": hit_chunks,
            "document_ids": document_ids,
            "documents": documents_payload,
            "golden_candidate": build_golden_candidate(
                feedback=feedback,
                user_message=user,
                assistant_message=assistant,
                hit_chunks=hit_chunks,
            ),
            "wiki_recompile_document_ids": document_ids,
        })
    return items


def append_eval_case(path: Path, candidate: Dict[str, Any]) -> Dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(existing, dict) and existing.get("id"):
                existing_ids.add(str(existing["id"]))
    if str(candidate["id"]) in existing_ids:
        return {"added": False, "path": str(path), "candidate": candidate}

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {"added": True, "path": str(path), "candidate": candidate}
