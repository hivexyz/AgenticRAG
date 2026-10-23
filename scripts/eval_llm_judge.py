"""Live LLM-judge evaluation for recorded AgenticRAG outputs.

This runner calls the configured chat model, so it is meant for manual or
scheduled environments where model endpoints are available. The deterministic
recorded eval remains the CI gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.models import llm_manager


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


def _extract_json_object(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    normalized = text.strip()
    try:
        parsed = json.loads(normalized)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        parsed = json.loads(normalized[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _score(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number > 1.0:
        number /= 100.0
    return min(max(number, 0.0), 1.0)


def parse_judgment(text: str) -> Dict[str, Any]:
    parsed = _extract_json_object(text)
    return {
        "groundedness": _score(parsed.get("groundedness")),
        "relevance": _score(parsed.get("relevance")),
        "completeness": _score(parsed.get("completeness")),
        "hallucination_risk": _score(parsed.get("hallucination_risk")),
        "reason": str(parsed.get("reason") or ""),
    }


def _source_snippets(result: Dict[str, Any], *, max_items: int = 8, max_chars: int = 800) -> List[str]:
    snippets: List[str] = []
    for item in result.get("search_results") or []:
        text = item.get("text") or item.get("content") or item.get("snippet")
        if text:
            snippets.append(str(text)[:max_chars])
    for card in result.get("evidence_cards") or []:
        text = card.get("snippet")
        if text:
            snippets.append(str(text)[:max_chars])
    for citation in result.get("citations") or []:
        for source in citation.get("sources") or []:
            text = source.get("snippet")
            if text:
                snippets.append(str(text)[:max_chars])

    deduped: List[str] = []
    for snippet in snippets:
        if snippet not in deduped:
            deduped.append(snippet)
        if len(deduped) >= max_items:
            break
    return deduped


def build_judge_prompt(case: Dict[str, Any], result: Dict[str, Any]) -> str:
    snippets = _source_snippets(result)
    context = "\n\n".join(f"[证据{i}] {snippet}" for i, snippet in enumerate(snippets, 1))
    if not context:
        context = result.get("context") or "无可用证据片段。"

    return f"""你是 RAG 答案质量评测裁判。请只基于给定证据、参考答案和用户问题打分。

用户问题：
{case.get("question") or result.get("query") or ""}

参考答案：
{case.get("reference_answer") or ""}

检索证据：
{context}

待评测答案：
{result.get("answer") or ""}

请输出 JSON 对象，不要输出其他内容：
{{
  "groundedness": 0到1,
  "relevance": 0到1,
  "completeness": 0到1,
  "hallucination_risk": 0到1,
  "reason": "一句中文理由"
}}"""


async def judge_case(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    response = await llm_manager.chat_completion(
        messages=[
            {"role": "system", "content": "你是严格、稳定的 RAG 评测裁判。"},
            {"role": "user", "content": build_judge_prompt(case, result)},
        ],
        temperature=0.0,
        max_tokens=300,
    )
    content = response.get("choices", [{}])[0].get("message", {}).get("content") or ""
    judgment = parse_judgment(content)
    return {
        "id": case["id"],
        "question": case.get("question"),
        "answer": result.get("answer"),
        **judgment,
    }


def summarize_judgments(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    items = list(rows)
    if not items:
        return {
            "case_count": 0,
            "avg_groundedness": 0.0,
            "avg_relevance": 0.0,
            "avg_completeness": 0.0,
            "avg_hallucination_risk": 0.0,
            "pass_count": 0,
        }
    return {
        "case_count": len(items),
        "avg_groundedness": mean(float(item.get("groundedness") or 0.0) for item in items),
        "avg_relevance": mean(float(item.get("relevance") or 0.0) for item in items),
        "avg_completeness": mean(float(item.get("completeness") or 0.0) for item in items),
        "avg_hallucination_risk": mean(float(item.get("hallucination_risk") or 0.0) for item in items),
        "pass_count": sum(
            1
            for item in items
            if float(item.get("groundedness") or 0.0) >= 0.75
            and float(item.get("relevance") or 0.0) >= 0.75
            and float(item.get("completeness") or 0.0) >= 0.65
            and float(item.get("hallucination_risk") or 0.0) <= 0.25
        ),
    }


def enforce_thresholds(
    summary: Dict[str, Any],
    *,
    min_groundedness: float,
    min_relevance: float,
    min_completeness: float,
    max_hallucination_risk: float,
) -> List[str]:
    failures = []
    if float(summary.get("avg_groundedness") or 0.0) < min_groundedness:
        failures.append("avg_groundedness below threshold")
    if float(summary.get("avg_relevance") or 0.0) < min_relevance:
        failures.append("avg_relevance below threshold")
    if float(summary.get("avg_completeness") or 0.0) < min_completeness:
        failures.append("avg_completeness below threshold")
    if float(summary.get("avg_hallucination_risk") or 0.0) > max_hallucination_risk:
        failures.append("avg_hallucination_risk above threshold")
    return failures


async def run(args: argparse.Namespace) -> Dict[str, Any]:
    cases = load_jsonl(Path(args.cases))
    results = load_jsonl(Path(args.results))
    result_by_id = {item["id"]: item for item in results}
    selected = cases[: args.limit] if args.limit else cases

    rows = []
    for case in selected:
        result = result_by_id.get(case["id"])
        if not result:
            rows.append({
                "id": case["id"],
                "groundedness": 0.0,
                "relevance": 0.0,
                "completeness": 0.0,
                "hallucination_risk": 1.0,
                "reason": "missing_result",
            })
            continue
        rows.append(await judge_case(case, result))

    output = {"summary": summarize_judgments(rows), "details": rows}
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live LLM-judge quality evaluation")
    parser.add_argument("--cases", default="tests/eval/eval_cases.jsonl")
    parser.add_argument("--results", default="tests/eval/recorded_results.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output")
    parser.add_argument("--min-groundedness", type=float, default=0.75)
    parser.add_argument("--min-relevance", type=float, default=0.75)
    parser.add_argument("--min-completeness", type=float, default=0.65)
    parser.add_argument("--max-hallucination-risk", type=float, default=0.25)
    args = parser.parse_args()

    llm_manager.connect()
    try:
        output = asyncio.run(run(args))
    finally:
        llm_manager.disconnect()

    print(json.dumps(output, ensure_ascii=False, indent=2))
    failures = enforce_thresholds(
        output["summary"],
        min_groundedness=args.min_groundedness,
        min_relevance=args.min_relevance,
        min_completeness=args.min_completeness,
        max_hallucination_risk=args.max_hallucination_risk,
    )
    if failures:
        print(json.dumps({"acceptance_pass": False, "failures": failures}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({"acceptance_pass": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
