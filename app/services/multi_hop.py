"""Sequential multi-hop retrieval execution."""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.context.assembler import trim_retrieval_results
from app.models import llm_manager
from app.services.retrieval import RetrievalOrchestrator, RetrievalProviderResult, RetrievalRequest, default_retrieval_orchestrator
from app.utils.logger import logger

SLOT_PLACEHOLDER_RE = re.compile(r"\{slots\.([^{}]+)\}")


class MultiHopError(RuntimeError):
    """Raised when multi-hop execution should fall back to normal retrieval."""


@dataclass
class HopPlan:
    hop: int
    purpose: str
    queries: List[str]
    slots: List[Dict[str, str]] = field(default_factory=list)
    depends_on: Optional[int] = None


@dataclass
class HopExecution:
    hop: int
    purpose: str
    rendered_queries: List[str]
    documents: List[Dict[str, Any]]
    ranked_groups: List[Tuple[str, List[Dict[str, Any]]]]
    extracted_slots: Dict[str, Optional[str]]
    errors: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    stopped_reason: Optional[str] = None

    def to_trace(self) -> Dict[str, Any]:
        provider_counts = self._provider_counts()
        return {
            "hop": self.hop,
            "purpose": self.purpose,
            "rendered_queries": self.rendered_queries,
            "extracted_slots": self.extracted_slots,
            "dense_results": provider_counts.get("vector", 0),
            "sparse_results": provider_counts.get("sparse", 0),
            "wiki_results": provider_counts.get("wiki", 0),
            "fused_results": len(self.documents),
            "elapsed_ms": round(self.elapsed_ms, 2),
            "errors": self.errors,
            "stopped_reason": self.stopped_reason,
        }

    def _provider_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for label, hits in self.ranked_groups:
            provider = label.split(":", 1)[0]
            counts[provider] = counts.get(provider, 0) + len(hits)
        return counts


class _SlotValues(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    normalized = (text or "").strip()
    if not normalized:
        return None
    try:
        parsed = json.loads(normalized)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", normalized, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class MultiHopExecutor:
    def __init__(self, retrieval_orchestrator: Optional[RetrievalOrchestrator] = None) -> None:
        self.retrieval_orchestrator = retrieval_orchestrator or default_retrieval_orchestrator

    async def execute(
        self,
        request: RetrievalRequest,
        hops: List[HopPlan],
    ) -> tuple[List[Dict[str, Any]], List[HopExecution]]:
        if not hops:
            raise MultiHopError("empty hop plan")

        started = time.perf_counter()
        all_groups: List[Tuple[str, List[Dict[str, Any]]]] = []
        executions: List[HopExecution] = []
        slot_values: Dict[str, Optional[str]] = {}
        previous_documents: List[Dict[str, Any]] = []
        max_hops = max(int(settings.MULTI_HOP_MAX_HOPS), 1)
        budget_seconds = max(float(settings.MULTI_HOP_TOTAL_TIMEOUT_SECONDS), 0.1)

        for hop in hops[:max_hops]:
            hop_started = time.perf_counter()
            remaining_budget = budget_seconds - (time.perf_counter() - started)
            if remaining_budget <= 0:
                executions.append(HopExecution(
                    hop=hop.hop,
                    purpose=hop.purpose,
                    rendered_queries=[],
                    documents=[],
                    ranked_groups=[],
                    extracted_slots={},
                    stopped_reason="timeout",
                ))
                break
            extracted_slots: Dict[str, Optional[str]] = {}
            if hop.slots:
                extracted_slots = await self._extract_slots(hop.slots, previous_documents)
                slot_values.update(extracted_slots)
                if any(value is None for value in extracted_slots.values()):
                    executions.append(HopExecution(
                        hop=hop.hop,
                        purpose=hop.purpose,
                        rendered_queries=[],
                        documents=[],
                        ranked_groups=[],
                        extracted_slots=extracted_slots,
                        elapsed_ms=(time.perf_counter() - hop_started) * 1000,
                        stopped_reason="slot_not_found",
                    ))
                    break

            rendered_queries = self._render_queries(
                hop.queries,
                slot_values,
                original_query=request.query,
                drop_original=hop.hop > 1,
            )
            if not rendered_queries:
                executions.append(HopExecution(
                    hop=hop.hop,
                    purpose=hop.purpose,
                    rendered_queries=[],
                    documents=[],
                    ranked_groups=[],
                    extracted_slots=extracted_slots,
                    elapsed_ms=(time.perf_counter() - hop_started) * 1000,
                    stopped_reason="empty_rendered_query",
                ))
                break

            try:
                groups, provider_results, _ = await asyncio.wait_for(
                    self.retrieval_orchestrator.retrieve_groups(request, rendered_queries),
                    timeout=max(remaining_budget, 0.1),
                )
            except asyncio.TimeoutError:
                executions.append(HopExecution(
                    hop=hop.hop,
                    purpose=hop.purpose,
                    rendered_queries=rendered_queries,
                    documents=[],
                    ranked_groups=[],
                    extracted_slots=extracted_slots,
                    elapsed_ms=(time.perf_counter() - hop_started) * 1000,
                    stopped_reason="timeout",
                ))
                break
            groups = [(f"{label}:h{hop.hop}", hits) for label, hits in groups]
            documents = self.retrieval_orchestrator.fuse_groups(request, groups)
            all_groups.extend(groups)
            previous_documents = documents
            errors = self._provider_errors(provider_results)
            execution = HopExecution(
                hop=hop.hop,
                purpose=hop.purpose,
                rendered_queries=rendered_queries,
                documents=documents,
                ranked_groups=groups,
                extracted_slots=extracted_slots,
                errors=errors,
                elapsed_ms=(time.perf_counter() - hop_started) * 1000,
            )
            executions.append(execution)

            if time.perf_counter() - started >= budget_seconds:
                execution.stopped_reason = "timeout"
                break

        if not all_groups:
            return [], executions

        return self.retrieval_orchestrator.fuse_groups(request, all_groups), executions

    async def _extract_slots(
        self,
        slots: List[Dict[str, str]],
        documents: List[Dict[str, Any]],
    ) -> Dict[str, Optional[str]]:
        if not slots:
            return {}
        if not documents:
            return {slot["name"]: None for slot in slots}

        try:
            return await asyncio.wait_for(
                self._extract_slots_once(slots, documents),
                timeout=max(float(settings.MULTI_HOP_SLOT_TIMEOUT_SECONDS), 0.1),
            )
        except Exception as exc:
            logger.warning(f"多跳槽位抽取失败: {exc}")
            return {slot["name"]: None for slot in slots}

    async def _extract_slots_once(
        self,
        slots: List[Dict[str, str]],
        documents: List[Dict[str, Any]],
    ) -> Dict[str, Optional[str]]:
        trimmed = await trim_retrieval_results(
            documents,
            max_docs=max(int(settings.MULTI_HOP_SLOT_EVIDENCE_DOCS), 1),
        )
        evidence = "\n\n".join(
            f"[文档{index + 1}] {item.get('text') or item.get('content') or ''}"
            for index, item in enumerate(trimmed["results"])
        )
        slot_block = "\n".join(f"- {slot['name']}：{slot['instruction']}" for slot in slots)
        response = await llm_manager.chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": "你是信息抽取器。只输出 JSON，不要输出解释。",
                },
                {
                    "role": "user",
                    "content": f"""根据检索证据，提取指定槽位。

槽位：
{slot_block}

证据：
{evidence}

只输出 JSON：{{"槽位名": "值或null"}}，不要输出其他内容。""",
                },
            ],
            temperature=0.0,
            max_tokens=200,
        )
        content = response.get("choices", [{}])[0].get("message", {}).get("content") or ""
        parsed = _extract_json_object(content) or {}
        output: Dict[str, Optional[str]] = {}
        for slot in slots:
            value = parsed.get(slot["name"])
            if value is None:
                output[slot["name"]] = None
                continue
            text = str(value).strip().strip("《》")
            output[slot["name"]] = text or None
        return output

    @staticmethod
    def _render_queries(
        queries: List[str],
        slots: Dict[str, Optional[str]],
        *,
        original_query: str,
        drop_original: bool,
    ) -> List[str]:
        rendered: List[str] = []
        slot_values = _SlotValues({key: value or "" for key, value in slots.items()})
        for query in queries:
            item = SLOT_PLACEHOLDER_RE.sub(lambda match: slot_values[match.group(1)], query or "")
            item = re.sub(r"\s+", " ", item).strip()
            if not item:
                continue
            if drop_original and item == original_query:
                continue
            if item not in rendered:
                rendered.append(item)
        return rendered

    @staticmethod
    def _provider_errors(provider_results: Dict[str, RetrievalProviderResult]) -> List[str]:
        return [f"{name}: {result.error}" for name, result in provider_results.items() if result.error]
