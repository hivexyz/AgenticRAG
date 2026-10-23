from tests.eval.eval_runner import enforce_thresholds, evaluate


def test_eval_runner_computes_recorded_metrics():
    cases = [
        {"id": "a", "must_hit_chunk_ids": [2], "must_mention": ["foo"], "expected_refusal": False},
        {"id": "b", "must_hit_chunk_ids": [], "must_mention": [], "expected_refusal": True},
    ]
    results = [
        {
            "id": "a",
            "answer": "foo answer",
            "search_results": [{"chunk_id": 1}, {"chunk_id": 2}],
            "citations": [{"sources": [{"chunk_id": 2}]}],
            "refusal": {"should_refuse": False},
            "latency_ms": 100,
        },
        {
            "id": "b",
            "answer": "no answer",
            "search_results": [],
            "citations": [],
            "refusal": {"should_refuse": True},
            "latency_ms": 300,
        },
    ]

    metrics = evaluate(cases, results, k=2)

    assert metrics["case_count"] == 2
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] == 0.5
    assert metrics["citation_accuracy"] == 1.0
    assert metrics["answer_must_mention_accuracy"] == 1.0
    assert metrics["refusal_accuracy"] == 1.0
    assert metrics["p95_latency_ms"] == 290.0


def test_eval_runner_threshold_enforcement_reports_failures():
    failures = enforce_thresholds(
        {
            "recall_at_k": 0.9,
            "citation_accuracy": 1.0,
            "answer_must_mention_accuracy": 0.8,
            "refusal_accuracy": 1.0,
            "p95_latency_ms": 3500.0,
        },
        min_recall_at_k=0.95,
        min_citation_accuracy=0.95,
        min_answer_must_mention_accuracy=0.95,
        min_refusal_accuracy=0.95,
        max_p95_latency_ms=3000.0,
    )

    assert any("recall_at_k" in failure for failure in failures)
    assert any("answer_must_mention_accuracy" in failure for failure in failures)
    assert any("p95_latency_ms" in failure for failure in failures)
