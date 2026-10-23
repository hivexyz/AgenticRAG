"""Deterministic offline evaluation for recorded AgenticRAG outputs.

This runner intentionally uses recorded fixtures instead of live retrieval/model
calls so it can run in CI and produce stable metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import quantiles
from typing import Any, Dict, Iterable, List, Sequence


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def _chunk_id(item: Dict[str, Any]) -> Any:
    return item.get("chunk_id") or (item.get("metadata") or {}).get("chunk_id")


def _search_chunk_ids(result: Dict[str, Any]) -> List[Any]:
    return [_chunk_id(item) for item in result.get("search_results") or [] if _chunk_id(item) is not None]


def _citation_chunk_ids(result: Dict[str, Any]) -> set[Any]:
    ids = set()
    for citation in result.get("citations") or []:
        for source in citation.get("sources") or []:
            chunk_id = _chunk_id(source)
            if chunk_id is not None:
                ids.add(chunk_id)
    return ids


def _contains_all(answer: str, terms: Iterable[str]) -> bool:
    return all(term in (answer or "") for term in terms)


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    return float(quantiles(values, n=20, method="inclusive")[18])


def evaluate(cases: List[Dict[str, Any]], results: List[Dict[str, Any]], *, k: int = 5) -> Dict[str, Any]:
    result_by_id = {item["id"]: item for item in results}
    rows = []
    for case in cases:
        result = result_by_id.get(case["id"], {})
        expected_hits = set(case.get("must_hit_chunk_ids") or [])
        retrieved = _search_chunk_ids(result)
        top_k = retrieved[:k]
        hit_positions = [index + 1 for index, chunk_id in enumerate(retrieved) if chunk_id in expected_hits]
        retrieval_hit = not expected_hits or any(chunk_id in expected_hits for chunk_id in top_k)
        reciprocal_rank = None if not expected_hits else (0.0 if not hit_positions else 1.0 / hit_positions[0])
        citation_ids = _citation_chunk_ids(result)
        citation_hit = not expected_hits or bool(citation_ids & expected_hits)
        answer_hit = _contains_all(result.get("answer") or "", case.get("must_mention") or [])
        expected_refusal = bool(case.get("expected_refusal"))
        actual_refusal = bool((result.get("refusal") or {}).get("should_refuse"))
        refusal_correct = expected_refusal == actual_refusal
        rows.append({
            "id": case["id"],
            "retrieval_hit": retrieval_hit,
            "reciprocal_rank": reciprocal_rank,
            "citation_hit": citation_hit,
            "answer_hit": answer_hit,
            "refusal_correct": refusal_correct,
            "latency_ms": float(result.get("latency_ms") or 0),
        })

    total = len(rows) or 1
    ranked_rows = [item for item in rows if item["reciprocal_rank"] is not None]
    ranked_total = len(ranked_rows) or 1
    return {
        "case_count": len(rows),
        "recall_at_k": sum(1 for item in rows if item["retrieval_hit"]) / total,
        "mrr": sum(item["reciprocal_rank"] for item in ranked_rows) / ranked_total,
        "citation_accuracy": sum(1 for item in rows if item["citation_hit"]) / total,
        "answer_must_mention_accuracy": sum(1 for item in rows if item["answer_hit"]) / total,
        "refusal_accuracy": sum(1 for item in rows if item["refusal_correct"]) / total,
        "p95_latency_ms": _p95([item["latency_ms"] for item in rows]),
        "details": rows,
    }


def enforce_thresholds(
    metrics: Dict[str, Any],
    *,
    min_recall_at_k: float,
    min_citation_accuracy: float,
    min_answer_must_mention_accuracy: float,
    min_refusal_accuracy: float,
    max_p95_latency_ms: float | None = None,
) -> List[str]:
    failures = []
    checks = [
        ("recall_at_k", metrics.get("recall_at_k", 0.0), min_recall_at_k, ">="),
        ("citation_accuracy", metrics.get("citation_accuracy", 0.0), min_citation_accuracy, ">="),
        (
            "answer_must_mention_accuracy",
            metrics.get("answer_must_mention_accuracy", 0.0),
            min_answer_must_mention_accuracy,
            ">=",
        ),
        ("refusal_accuracy", metrics.get("refusal_accuracy", 0.0), min_refusal_accuracy, ">="),
    ]
    for name, actual, expected, operator in checks:
        if actual < expected:
            failures.append(f"{name} {actual:.4f} {operator} {expected:.4f} 未达标")

    if max_p95_latency_ms is not None:
        actual_latency = float(metrics.get("p95_latency_ms") or 0.0)
        if actual_latency > max_p95_latency_ms:
            failures.append(
                f"p95_latency_ms {actual_latency:.1f} <= {max_p95_latency_ms:.1f} 未达标"
            )

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate recorded AgenticRAG outputs")
    parser.add_argument("--cases", default="tests/eval/eval_cases.jsonl")
    parser.add_argument("--results", default="tests/eval/recorded_results.jsonl")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--min-recall-at-k", type=float, default=None)
    parser.add_argument("--min-citation-accuracy", type=float, default=None)
    parser.add_argument("--min-answer-must-mention-accuracy", type=float, default=None)
    parser.add_argument("--min-refusal-accuracy", type=float, default=None)
    parser.add_argument("--max-p95-latency-ms", type=float, default=None)
    args = parser.parse_args()
    metrics = evaluate(load_jsonl(Path(args.cases)), load_jsonl(Path(args.results)), k=args.k)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    threshold_args = [
        args.min_recall_at_k,
        args.min_citation_accuracy,
        args.min_answer_must_mention_accuracy,
        args.min_refusal_accuracy,
    ]
    if any(value is not None for value in threshold_args) or args.max_p95_latency_ms is not None:
        failures = enforce_thresholds(
            metrics,
            min_recall_at_k=args.min_recall_at_k if args.min_recall_at_k is not None else 0.0,
            min_citation_accuracy=args.min_citation_accuracy if args.min_citation_accuracy is not None else 0.0,
            min_answer_must_mention_accuracy=(
                args.min_answer_must_mention_accuracy
                if args.min_answer_must_mention_accuracy is not None
                else 0.0
            ),
            min_refusal_accuracy=args.min_refusal_accuracy if args.min_refusal_accuracy is not None else 0.0,
            max_p95_latency_ms=args.max_p95_latency_ms,
        )
        if failures:
            print(json.dumps({"acceptance_pass": False, "failures": failures}, ensure_ascii=False, indent=2), file=sys.stderr)
            raise SystemExit(1)
        print(json.dumps({"acceptance_pass": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
