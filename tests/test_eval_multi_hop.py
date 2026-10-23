from pathlib import Path

import pytest

from scripts import eval_multi_hop
from scripts.eval_multi_hop import enforce_thresholds, load_cases, _normalize_output, summarize_outputs


def test_recorded_multi_hop_golden_meets_acceptance_thresholds():
    cases = load_cases(Path("tests/fixtures/multi_hop_golden.jsonl"))
    recorded = {item["q"]: item for item in load_cases(Path("tests/fixtures/multi_hop_golden_recorded.jsonl"))}
    outputs = [_normalize_output(case, recorded[case["q"]]) for case in cases]

    summary = summarize_outputs(outputs)["summary"]

    assert summary["total"] == 15
    assert summary["multi_hop_cases"] == 10
    assert summary["intermediate_entity_hits"] == 10
    assert summary["false_multi_hop"] <= 1
    assert summary["must_mention_pass"] == 15
    assert summary["acceptance_pass"] >= 12


def test_multi_hop_threshold_enforcement_fails_when_below_threshold():
    with pytest.raises(SystemExit):
        enforce_thresholds(
            {"total": 15, "acceptance_pass": 11, "false_multi_hop": 0, "must_mention_pass": 15},
            min_acceptance=12,
            max_false_multi_hop=1,
            require_all_must_mention=True,
        )


@pytest.mark.asyncio
async def test_live_preflight_fails_fast_when_dependencies_missing(monkeypatch):
    class MissingLLM:
        client = None

        def connect(self):
            return None

    class MissingEmbedding:
        client = None

        def connect(self):
            return None

    class NoopReranker:
        def connect(self):
            return None

    class BrokenSessionMaker:
        def __call__(self):
            raise RuntimeError("db down")

    class BrokenVectorStore:
        def connect(self):
            return None

        async def ensure_ready(self):
            raise RuntimeError("vector down")

    monkeypatch.setattr(eval_multi_hop, "llm_manager", MissingLLM())
    monkeypatch.setattr(eval_multi_hop, "embedding_manager", MissingEmbedding())
    monkeypatch.setattr(eval_multi_hop, "reranker_manager", NoopReranker())
    monkeypatch.setattr(eval_multi_hop, "async_session_maker", BrokenSessionMaker())
    monkeypatch.setattr(eval_multi_hop, "vector_store", BrokenVectorStore())

    with pytest.raises(SystemExit) as exc:
        await eval_multi_hop.prepare_live_dependencies()

    assert "dependencies are not ready" in str(exc.value)
    assert "LLM client is not initialized" in str(exc.value)

    result = await eval_multi_hop.check_live_dependencies()
    assert result["ok"] is False
    assert result["recommendations"]
