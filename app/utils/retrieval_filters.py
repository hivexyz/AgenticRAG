"""Shared helpers for executing planner filters in retrieval backends."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _as_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item is not None and item != ""]
    return [value]


def int_filter_values(filters: Optional[Dict[str, Any]], *keys: str) -> List[int]:
    values: List[int] = []
    for key in keys:
        for item in _as_list((filters or {}).get(key)):
            try:
                number = int(item)
            except (TypeError, ValueError):
                continue
            if number not in values:
                values.append(number)
    return values


def string_filter_values(filters: Optional[Dict[str, Any]], *keys: str) -> List[str]:
    values: List[str] = []
    for key in keys:
        for item in _as_list((filters or {}).get(key)):
            value = str(item).strip()
            if value and value not in values:
                values.append(value)
    return values


def document_id_values(filters: Optional[Dict[str, Any]]) -> List[int]:
    return int_filter_values(filters, "document_id", "document_ids", "documents")


def file_type_values(filters: Optional[Dict[str, Any]]) -> List[str]:
    return string_filter_values(filters, "file_type", "file_types")


def knowledge_base_values(filters: Optional[Dict[str, Any]]) -> List[str]:
    return string_filter_values(filters, "knowledge_base", "knowledge_bases")


def source_type_values(filters: Optional[Dict[str, Any]]) -> List[str]:
    return string_filter_values(filters, "source_type", "source_types")


def _metadata_value(item: Dict[str, Any], key: str) -> Any:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    document_metadata = metadata.get("document_metadata") if isinstance(metadata.get("document_metadata"), dict) else {}
    for container in (item, metadata, document_metadata):
        value = container.get(key)
        if value is not None and value != "":
            return value
    return None


def _matches_any_string(value: Any, allowed: Iterable[str], *, case_sensitive: bool = True) -> bool:
    allowed_values = [item for item in allowed if item]
    if not allowed_values:
        return True
    if value is None:
        return False
    current = str(value)
    if case_sensitive:
        return current in allowed_values
    return current.lower() in {item.lower() for item in allowed_values}


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def matches_retrieval_filters(item: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
    """Apply supported planner filters to one hydrated retrieval hit."""
    if not filters:
        return True

    document_ids = document_id_values(filters)
    if document_ids:
        try:
            document_id = int(_metadata_value(item, "document_id"))
        except (TypeError, ValueError):
            return False
        if document_id not in document_ids:
            return False

    knowledge_bases = knowledge_base_values(filters)
    if knowledge_bases and not _matches_any_string(_metadata_value(item, "knowledge_base"), knowledge_bases):
        return False

    file_types = file_type_values(filters)
    if file_types and not _matches_any_string(_metadata_value(item, "file_type"), file_types, case_sensitive=False):
        return False

    source_types = source_type_values(filters)
    if source_types and not _matches_any_string(_metadata_value(item, "source_type"), source_types):
        return False

    uploaded_after = _parse_datetime((filters or {}).get("uploaded_after") or (filters or {}).get("created_after"))
    uploaded_before = _parse_datetime((filters or {}).get("uploaded_before") or (filters or {}).get("created_before"))
    if uploaded_after or uploaded_before:
        item_time = _parse_datetime(_metadata_value(item, "uploaded_at") or _metadata_value(item, "created_at"))
        if item_time is None:
            return False
        if uploaded_after and item_time < uploaded_after:
            return False
        if uploaded_before and item_time > uploaded_before:
            return False

    return True


def filter_retrieval_hits(hits: Iterable[Dict[str, Any]], filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [hit for hit in hits if matches_retrieval_filters(hit, filters)]


def _quote_milvus_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _or_clauses(field: str, values: Iterable[Any], *, string_values_: bool = False) -> Optional[str]:
    clauses = []
    for value in values:
        literal = _quote_milvus_string(str(value)) if string_values_ else str(int(value))
        clauses.append(f'metadata["{field}"] == {literal}')
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return "(" + " or ".join(clauses) + ")"


def build_milvus_metadata_expr(filters: Optional[Dict[str, Any]]) -> Optional[str]:
    """Build a Milvus JSON metadata expression from supported filters only."""
    if not filters:
        return None

    clauses = [
        _or_clauses("document_id", document_id_values(filters)),
        _or_clauses("knowledge_base", knowledge_base_values(filters), string_values_=True),
        _or_clauses("file_type", [item.lower() for item in file_type_values(filters)], string_values_=True),
        _or_clauses("source_type", source_type_values(filters), string_values_=True),
    ]
    clauses = [clause for clause in clauses if clause]
    if not clauses:
        return None
    return " and ".join(f"({clause})" for clause in clauses)


def _in_clause(column: str, values: List[Any], prefix: str, params: Dict[str, Any]) -> Optional[str]:
    placeholders = []
    for index, value in enumerate(values):
        name = f"{prefix}_{index}"
        params[name] = value
        placeholders.append(f":{name}")
    if not placeholders:
        return None
    return f"{column} IN ({', '.join(placeholders)})"


def build_pgvector_filter_sql(filters: Optional[Dict[str, Any]]) -> Tuple[List[str], Dict[str, Any]]:
    """Build safe SQL snippets for the pgvector metadata table."""
    params: Dict[str, Any] = {}
    clauses = [
        _in_clause("document_id", document_id_values(filters), "filter_document_id", params),
        _in_clause("LOWER(metadata ->> 'file_type')", [item.lower() for item in file_type_values(filters)], "filter_file_type", params),
        _in_clause("metadata ->> 'knowledge_base'", knowledge_base_values(filters), "filter_knowledge_base", params),
        _in_clause("metadata ->> 'source_type'", source_type_values(filters), "filter_source_type", params),
    ]
    return [clause for clause in clauses if clause], params


def build_sparse_filter_sql(filters: Optional[Dict[str, Any]]) -> Tuple[List[str], Dict[str, Any]]:
    """Build safe SQL snippets for document_chunks joined with documents."""
    params: Dict[str, Any] = {}
    clauses = [
        _in_clause("dc.document_id", document_id_values(filters), "filter_document_id", params),
        _in_clause("LOWER(d.file_type)", [item.lower() for item in file_type_values(filters)], "filter_file_type", params),
        _in_clause("COALESCE(dc.chunk_metadata ->> 'knowledge_base', d.doc_metadata::jsonb ->> 'knowledge_base')", knowledge_base_values(filters), "filter_knowledge_base", params),
        _in_clause("dc.chunk_metadata ->> 'source_type'", source_type_values(filters), "filter_source_type", params),
    ]
    return [clause for clause in clauses if clause], params
