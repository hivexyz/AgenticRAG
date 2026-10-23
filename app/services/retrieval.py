"""Composable retrieval providers for the AgenticRAG graph."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Protocol

from app.config import settings
from app.database.hybrid_search import hydrate_vector_hits, reciprocal_rank_fusion, sparse_search_chunks
from app.database.postgres import async_session_maker
from app.database.vector_store import vector_store
from app.models import embedding_manager
from app.services.wiki import search_wiki_pages
from app.utils.retrieval_filters import build_milvus_metadata_expr, filter_retrieval_hits


@dataclass(frozen=True)
class RetrievalRequest:
    tenant_id: str
    query: str
    route: str
    top_k: int
    dense_top_k: int
    sparse_top_k: int
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalProviderResult:
    name: str
    hits: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class RetrievalResponse:
    documents: List[Dict[str, Any]]
    provider_results: Dict[str, RetrievalProviderResult]
    queries: List[str] = field(default_factory=list)

    @property
    def vector_error(self) -> Optional[str]:
        return self.provider_results.get("vector", RetrievalProviderResult("vector")).error

    @property
    def sparse_error(self) -> Optional[str]:
        return self.provider_results.get("sparse", RetrievalProviderResult("sparse")).error

    @property
    def wiki_error(self) -> Optional[str]:
        return self.provider_results.get("wiki", RetrievalProviderResult("wiki")).error

    def attempt_payload(self, *, attempt_number: int, query: str, route: str) -> Dict[str, Any]:
        vector_hits = self.provider_results.get("vector", RetrievalProviderResult("vector")).hits
        sparse_hits = self.provider_results.get("sparse", RetrievalProviderResult("sparse")).hits
        wiki_hits = self.provider_results.get("wiki", RetrievalProviderResult("wiki")).hits
        raw_results_total = sum(len(result.hits) for result in self.provider_results.values())
        provider_errors = [result.error for result in self.provider_results.values() if result.error]
        payload: Dict[str, Any] = {
            "attempt": attempt_number,
            "query": query,
            "route": route,
            "queries": self.queries or [query],
            "query_count": len(self.queries or [query]),
            "dense_results": len(vector_hits),
            "sparse_results": len(sparse_hits),
            "wiki_results": len(wiki_hits),
            "raw_results_total": raw_results_total,
            "fused_results": len(self.documents),
            "merged_results": len(self.documents),
            "degraded": bool(provider_errors and self.documents),
        }
        for key, result in self.provider_results.items():
            if key not in {"vector", "sparse", "wiki"}:
                payload[f"{key}_results"] = len(result.hits)
            if result.error:
                payload[f"{key}_error"] = result.error
        return payload


class RetrievalProvider(Protocol):
    name: str

    async def retrieve(self, request: RetrievalRequest) -> List[Dict[str, Any]]:
        ...


class VectorRetrievalProvider:
    name = "vector"

    async def retrieve(self, request: RetrievalRequest) -> List[Dict[str, Any]]:
        query_embedding = await embedding_manager.create_embedding(request.query)
        vector_expr = None
        vector_params = None
        if vector_store.backend_name == "milvus":
            vector_expr = build_milvus_metadata_expr(request.filters)
        elif vector_store.backend_name == "pgvector":
            vector_params = {"metadata_filters": request.filters}
        vector_pages = await vector_store.search_vectors(
            query_vectors=[query_embedding],
            top_k=request.dense_top_k,
            expr=vector_expr,
            params=vector_params,
            tenant_id=request.tenant_id,
        )
        vector_hits: List[Dict[str, Any]] = []
        if vector_pages and vector_pages[0]:
            for hit in vector_pages[0]:
                doc = dict(hit.get("metadata", {}) or {})
                doc["id"] = hit.get("id")
                doc["distance"] = hit.get("distance")
                doc["score"] = hit.get("distance")
                doc["vector_score"] = hit.get("score", hit.get("distance"))
                vector_hits.append(doc)
            try:
                hydrated_hits = await hydrate_vector_hits(vector_hits, tenant_id=request.tenant_id)
                return filter_retrieval_hits(hydrated_hits, request.filters)
            except Exception:
                return filter_retrieval_hits(vector_hits, request.filters)
        return filter_retrieval_hits(vector_hits, request.filters)


class SparseRetrievalProvider:
    name = "sparse"

    async def retrieve(self, request: RetrievalRequest) -> List[Dict[str, Any]]:
        if request.route not in {"hybrid", "multi_hop"} or request.sparse_top_k <= 0:
            return []
        return await sparse_search_chunks(
            request.query,
            tenant_id=request.tenant_id,
            top_k=request.sparse_top_k,
            filters=request.filters,
        )


class WikiRetrievalProvider:
    name = "wiki"

    async def retrieve(self, request: RetrievalRequest) -> List[Dict[str, Any]]:
        async with async_session_maker() as session:
            return await search_wiki_pages(
                session=session,
                tenant_id=request.tenant_id,
                query=request.query,
                knowledge_base=request.filters.get("knowledge_base"),
                top_k=min(max(request.top_k, 3), 8),
            )


class RetrievalOrchestrator:
    def __init__(self, providers: Optional[List[RetrievalProvider]] = None) -> None:
        self.providers = providers or [
            VectorRetrievalProvider(),
            SparseRetrievalProvider(),
            WikiRetrievalProvider(),
        ]

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        return await self.retrieve_many(request, [request.query])

    async def retrieve_many(self, request: RetrievalRequest, queries: List[str]) -> RetrievalResponse:
        ranked_groups, provider_results, normalized_queries = await self.retrieve_groups(request, queries)
        documents = self.fuse_groups(request, ranked_groups)
        return RetrievalResponse(
            documents=documents,
            provider_results=provider_results,
            queries=normalized_queries,
        )

    async def retrieve_groups(
        self,
        request: RetrievalRequest,
        queries: List[str],
    ) -> tuple[List[tuple[str, List[Dict[str, Any]]]], Dict[str, RetrievalProviderResult], List[str]]:
        """Run one retrieval round and return unfused ranked groups plus provider results."""
        normalized_queries = self._normalize_queries(request.query, queries)
        semaphore = asyncio.Semaphore(max(int(settings.RETRIEVAL_MAX_CONCURRENCY), 1))
        tasks = []
        labels = []
        for query_index, query in enumerate(normalized_queries, 1):
            query_request = replace(request, query=query)
            for provider in self.providers:
                labels.append((query_index, provider.name))
                tasks.append(self._run_provider(provider, query_request, semaphore))

        results = await asyncio.gather(*tasks) if tasks else []
        provider_results: Dict[str, RetrievalProviderResult] = {}
        ranked_groups: List[tuple[str, List[Dict[str, Any]]]] = []
        for (query_index, provider_name), result in zip(labels, results):
            aggregate = provider_results.setdefault(provider_name, RetrievalProviderResult(provider_name))
            if result.hits:
                aggregate.hits.extend(result.hits)
                ranked_groups.append((f"{provider_name}:q{query_index}", result.hits))
            if result.error:
                aggregate.error = " | ".join([item for item in [aggregate.error, result.error] if item])

        return ranked_groups, provider_results, normalized_queries

    def fuse_groups(
        self,
        request: RetrievalRequest,
        ranked_groups: List[tuple[str, List[Dict[str, Any]]]],
    ) -> List[Dict[str, Any]]:
        """Fuse ranked groups using the same RRF semantics as normal retrieval."""
        return self._fuse_ranked_groups(request, ranked_groups)

    async def _run_provider(
        self,
        provider: RetrievalProvider,
        request: RetrievalRequest,
        semaphore: asyncio.Semaphore,
    ) -> RetrievalProviderResult:
        async with semaphore:
            try:
                hits = await asyncio.wait_for(
                    provider.retrieve(request),
                    timeout=max(float(settings.RETRIEVAL_PROVIDER_TIMEOUT_SECONDS), 0.1),
                )
                return RetrievalProviderResult(provider.name, hits=hits)
            except asyncio.TimeoutError:
                return RetrievalProviderResult(
                    provider.name,
                    error=f"{provider.name} retrieval timed out after {settings.RETRIEVAL_PROVIDER_TIMEOUT_SECONDS}s",
                )
            except Exception as exc:
                return RetrievalProviderResult(provider.name, error=str(exc))

    def _fuse_results(
        self,
        request: RetrievalRequest,
        provider_results: Dict[str, RetrievalProviderResult],
    ) -> List[Dict[str, Any]]:
        return self._fuse_ranked_groups(
            request,
            [(name, result.hits) for name, result in provider_results.items() if result.hits],
        )

    def _fuse_ranked_groups(
        self,
        request: RetrievalRequest,
        ranked_groups: List[tuple[str, List[Dict[str, Any]]]],
    ) -> List[Dict[str, Any]]:
        if request.route in {"hybrid", "multi_hop"}:
            ranked_lists, source_names = self._ranked_lists(ranked_groups)
            return reciprocal_rank_fusion(
                ranked_lists,
                source_names,
                top_k=max(request.top_k, min(request.dense_top_k + request.sparse_top_k, 50)),
            )
        non_sparse_results = [
            (name, hits)
            for name, hits in ranked_groups
            if not name.startswith("sparse")
        ]
        ranked_lists, source_names = self._ranked_lists(non_sparse_results, limit=request.top_k)
        return reciprocal_rank_fusion(
            ranked_lists,
            source_names,
            top_k=request.top_k,
        )

    @staticmethod
    def _ranked_lists(
        ranked_groups: List[tuple[str, List[Dict[str, Any]]]],
        *,
        limit: Optional[int] = None,
    ) -> tuple[List[List[Dict[str, Any]]], List[str]]:
        ranked_lists = []
        source_names = []
        for name, hits in ranked_groups:
            hits = hits[:limit] if limit is not None else hits
            ranked_lists.append(hits)
            source_names.append(name)
        return ranked_lists, source_names

    @staticmethod
    def _normalize_queries(primary_query: str, queries: List[str]) -> List[str]:
        max_queries = max(int(settings.AGENTIC_RAG_MAX_SUB_QUERIES), 1)
        normalized = []
        for item in [primary_query, *(queries or [])]:
            query = str(item or "").strip()
            if not query or query in normalized:
                continue
            normalized.append(query)
            if len(normalized) >= max_queries:
                break
        return normalized or [primary_query]


default_retrieval_orchestrator = RetrievalOrchestrator()
