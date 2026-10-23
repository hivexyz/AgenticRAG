from scripts.eval_llm_judge import enforce_thresholds, parse_judgment, summarize_judgments


def test_parse_judgment_extracts_json_and_normalizes_scores():
    result = parse_judgment(
        '评测如下：{"groundedness":85,"relevance":0.9,"completeness":0.8,"hallucination_risk":10,"reason":"证据充分"}'
    )

    assert result["groundedness"] == 0.85
    assert result["relevance"] == 0.9
    assert result["completeness"] == 0.8
    assert result["hallucination_risk"] == 0.1
    assert result["reason"] == "证据充分"


def test_llm_judge_summary_and_thresholds():
    summary = summarize_judgments([
        {"groundedness": 0.9, "relevance": 0.8, "completeness": 0.7, "hallucination_risk": 0.1},
        {"groundedness": 0.7, "relevance": 0.8, "completeness": 0.6, "hallucination_risk": 0.2},
    ])

    assert summary["case_count"] == 2
    assert summary["avg_groundedness"] == 0.8
    assert summary["pass_count"] == 1
    assert enforce_thresholds(
        summary,
        min_groundedness=0.75,
        min_relevance=0.75,
        min_completeness=0.6,
        max_hallucination_risk=0.25,
    ) == []
    assert enforce_thresholds(
        summary,
        min_groundedness=0.85,
        min_relevance=0.75,
        min_completeness=0.6,
        max_hallucination_risk=0.25,
    ) == ["avg_groundedness below threshold"]
