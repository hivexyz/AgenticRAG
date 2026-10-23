"""Manual multi-hop evaluation runner.

This script depends on live model and retrieval backends. It is intentionally not
part of CI. Run from the repository root after configuring .env:

    python scripts/eval_multi_hop.py --cases tests/fixtures/multi_hop_golden.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agents import agentic_rag_manager
from app.config import settings
from app.database.postgres import async_session_maker, postgres_manager
from app.database.vector_store import vector_store
from app.models import embedding_manager, llm_manager, reranker_manager
from sqlalchemy import text


def load_cases(path: Path) -> List[Dict[str, Any]]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


def _contains_all(answer: str, terms: Iterable[str]) -> bool:
    return all(term in (answer or "") for term in terms)


def _normalize_output(case: Dict[str, Any], output: Dict[str, Any]) -> Dict[str, Any]:
    answer = output.get("answer") or ""
    rendered_queries = output.get("rendered_queries") or [
        query
        for hop in (output.get("multi_hop_trace") or [])
        for query in (hop.get("rendered_queries") or [])
    ]
    intermediate = case.get("intermediate_entity")
    intermediate_hit = True
    if intermediate:
        intermediate_hit = any(intermediate in query for query in rendered_queries) or intermediate in answer
    return {
        **output,
        "q": case["q"],
        "rendered_queries": rendered_queries,
        "answer": answer,
        "must_mention_pass": _contains_all(answer, case.get("must_mention") or []),
        "intermediate_entity": intermediate,
        "intermediate_hit": intermediate_hit,
    }


def summarize_outputs(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    multi_hop_cases = [item for item in items if item["intermediate_entity"]]
    distractors = [item for item in items if not item["intermediate_entity"]]
    intermediate_pass = sum(1 for item in multi_hop_cases if item["intermediate_hit"])
    false_multi_hop = sum(1 for item in distractors if item.get("route") == "multi_hop")
    must_mention_pass = sum(1 for item in items if item.get("must_mention_pass"))
    acceptance_pass = intermediate_pass + (len(distractors) - false_multi_hop)
    return {
        "summary": {
            "total": len(items),
            "multi_hop_cases": len(multi_hop_cases),
            "intermediate_entity_hits": intermediate_pass,
            "distractors": len(distractors),
            "false_multi_hop": false_multi_hop,
            "must_mention_pass": must_mention_pass,
            "acceptance_pass": acceptance_pass,
        }
    }


def enforce_thresholds(summary: Dict[str, Any], *, min_acceptance: int, max_false_multi_hop: int, require_all_must_mention: bool) -> None:
    failures = []
    if int(summary.get("acceptance_pass") or 0) < min_acceptance:
        failures.append(f"acceptance_pass<{min_acceptance}")
    if int(summary.get("false_multi_hop") or 0) > max_false_multi_hop:
        failures.append(f"false_multi_hop>{max_false_multi_hop}")
    if require_all_must_mention and int(summary.get("must_mention_pass") or 0) < int(summary.get("total") or 0):
        failures.append("must_mention_pass<total")
    if failures:
        raise SystemExit("multi-hop golden thresholds failed: " + ", ".join(failures))


def _check_base_url_reachable(label: str, url: str | None) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=2):
            return None
    except OSError as exc:
        return f"{label} endpoint is not reachable at {parsed.hostname}:{port}: {exc}"


async def check_live_dependencies() -> Dict[str, Any]:
    """Initialize/check dependencies needed when running against live model/retrieval backends."""
    errors = []
    checks: Dict[str, Dict[str, Any]] = {}
    recommendations = []
    try:
        llm_manager.connect()
        if llm_manager.client is None:
            error = "LLM client is not initialized; check OPENAI_API_KEY/OPENAI_BASE_URL"
            checks["llm"] = {"ok": False, "error": error}
            errors.append(error)
        else:
            endpoint_error = _check_base_url_reachable("LLM", settings.OPENAI_BASE_URL)
            if endpoint_error:
                checks["llm"] = {"ok": False, "error": endpoint_error}
                errors.append(endpoint_error)
                recommendations.append("Start or configure the OpenAI-compatible LLM endpoint; check OPENAI_BASE_URL and OPENAI_API_KEY")
            else:
                checks["llm"] = {"ok": True}
    except Exception as exc:
        error = f"LLM client initialization failed: {exc}"
        checks["llm"] = {"ok": False, "error": error}
        errors.append(error)

    try:
        embedding_manager.connect()
        if embedding_manager.client is None:
            error = "Embedding client is not initialized; check OPENAI_API_KEY/OPENAI_EMBEDDING_BASE_URL"
            checks["embedding"] = {"ok": False, "error": error}
            errors.append(error)
        else:
            endpoint_error = _check_base_url_reachable("Embedding", settings.OPENAI_EMBEDDING_BASE_URL or settings.OPENAI_BASE_URL)
            if endpoint_error:
                checks["embedding"] = {"ok": False, "error": endpoint_error}
                errors.append(endpoint_error)
                recommendations.append("Start or configure the embedding endpoint; check OPENAI_EMBEDDING_BASE_URL or OPENAI_BASE_URL")
            else:
                checks["embedding"] = {"ok": True}
    except Exception as exc:
        error = f"Embedding client initialization failed: {exc}"
        checks["embedding"] = {"ok": False, "error": error}
        errors.append(error)

    try:
        reranker_manager.connect()
        endpoint_error = _check_base_url_reachable("Reranker", settings.OPENAI_RERANKER_BASE_URL)
        if endpoint_error:
            checks["reranker"] = {"ok": False, "error": endpoint_error}
            errors.append(endpoint_error)
            recommendations.append("Start or configure the reranker endpoint; check OPENAI_RERANKER_BASE_URL")
        else:
            checks["reranker"] = {"ok": True}
    except Exception as exc:
        error = f"Reranker client initialization failed: {exc}"
        checks["reranker"] = {"ok": False, "error": error}
        errors.append(error)

    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = {"ok": True}
    except Exception as exc:
        error = f"PostgreSQL is not reachable: {exc}"
        checks["postgres"] = {"ok": False, "error": error}
        errors.append(error)
        recommendations.append("Start PostgreSQL and run migrations, for example: docker compose up -d postgres && docker compose run --rm api uv run alembic upgrade head")

    try:
        vector_store.connect()
        await vector_store.ensure_ready()
        checks["vector_store"] = {"ok": True}
    except Exception as exc:
        error = f"Vector store is not reachable: {exc}"
        checks["vector_store"] = {"ok": False, "error": error}
        errors.append(error)
        recommendations.append("Start the configured vector store, for example: docker compose up -d etcd minio milvus")

    return {
        "ok": not errors,
        "checks": checks,
        "errors": errors,
        "recommendations": list(dict.fromkeys(recommendations)),
    }


async def prepare_live_dependencies() -> None:
    result = await check_live_dependencies()
    errors = result["errors"]

    if errors:
        raise SystemExit(
            "live multi-hop evaluation dependencies are not ready:\n- "
            + "\n- ".join(errors)
            + "\nUse --recorded-results for offline validation, or start/configure the live stack first."
        )


async def run_case(case: Dict[str, Any], *, tenant_id: str) -> Dict[str, Any]:
    result = await agentic_rag_manager.query(case["q"], tenant_id=tenant_id)
    answer = result.get("answer") or ""
    trace = result.get("multi_hop_trace") or []
    analysis = result.get("query_analysis") or {}
    rendered_queries = [
        query
        for hop in trace
        for query in (hop.get("rendered_queries") or [])
    ]
    intermediate = case.get("intermediate_entity")
    return _normalize_output(case, {
        "q": case["q"],
        "route": analysis.get("route"),
        "hops": analysis.get("hops") or [],
        "rendered_queries": rendered_queries,
        "answer": answer,
        "intermediate_entity": intermediate,
        "multi_hop_trace": trace,
    })


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run manual multi-hop golden set evaluation")
    parser.add_argument("--cases", default="tests/fixtures/multi_hop_golden.jsonl")
    parser.add_argument("--recorded-results", default=None, help="Evaluate recorded JSONL outputs instead of live model/backends")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--enforce-thresholds", action="store_true", help="Exit non-zero when golden-set acceptance thresholds fail")
    parser.add_argument("--preflight-only", action="store_true", help="Only check live dependencies and exit")
    parser.add_argument("--json-summary", action="store_true", help="Print machine-readable JSON for preflight failures")
    parser.add_argument("--skip-live-preflight", action="store_true", help="Skip live dependency checks")
    parser.add_argument("--min-acceptance", type=int, default=12)
    parser.add_argument("--max-false-multi-hop", type=int, default=1)
    parser.add_argument("--allow-missing-mentions", action="store_true")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    if args.preflight_only:
        result = await check_live_dependencies()
        print(json.dumps({"preflight": result}, ensure_ascii=False))
        if not result["ok"]:
            raise SystemExit(1)
        await postgres_manager.close_db()
        vector_store.disconnect()
        return

    if args.recorded_results:
        result_by_q = {item["q"]: item for item in load_cases(Path(args.recorded_results))}
        outputs = [_normalize_output(case, result_by_q.get(case["q"], {})) for case in cases]
    else:
        if not args.skip_live_preflight:
            try:
                await prepare_live_dependencies()
            except SystemExit as exc:
                if args.json_summary:
                    result = await check_live_dependencies()
                    print(json.dumps({"preflight": result}, ensure_ascii=False))
                raise exc
        outputs = []
        for case in cases:
            outputs.append(await run_case(case, tenant_id=args.tenant_id))

    for item in outputs:
        print(json.dumps(item, ensure_ascii=False))
    summary_payload = summarize_outputs(outputs)
    print(json.dumps(summary_payload, ensure_ascii=False))
    if args.enforce_thresholds:
        enforce_thresholds(
            summary_payload["summary"],
            min_acceptance=args.min_acceptance,
            max_false_multi_hop=args.max_false_multi_hop,
            require_all_must_mention=not args.allow_missing_mentions,
        )
    if not args.recorded_results:
        await postgres_manager.close_db()
        vector_store.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
