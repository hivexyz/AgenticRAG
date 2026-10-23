import pytest

from app.workers import wiki_worker


@pytest.mark.asyncio
async def test_run_wiki_worker_once_processes_due_jobs(monkeypatch):
    calls = []

    async def fake_find_due_wiki_compile_job_ids(limit=None):
        assert limit == 2
        return [11, 12]

    async def fake_run_wiki_compile_job(job_id, worker_id=None):
        calls.append((job_id, worker_id))

    monkeypatch.setattr(wiki_worker, "find_due_wiki_compile_job_ids", fake_find_due_wiki_compile_job_ids)
    monkeypatch.setattr(wiki_worker, "run_wiki_compile_job", fake_run_wiki_compile_job)

    result = await wiki_worker.run_wiki_worker_once(worker_id="worker-test", batch_size=2)

    assert result == {"worker_id": "worker-test", "job_ids": [11, 12], "processed_count": 2}
    assert calls == [(11, "worker-test"), (12, "worker-test")]


@pytest.mark.asyncio
async def test_run_wiki_worker_once_handles_empty_queue(monkeypatch):
    async def fake_find_due_wiki_compile_job_ids(limit=None):
        return []

    async def should_not_run(*args, **kwargs):
        raise AssertionError("worker should not run jobs when queue is empty")

    monkeypatch.setattr(wiki_worker, "find_due_wiki_compile_job_ids", fake_find_due_wiki_compile_job_ids)
    monkeypatch.setattr(wiki_worker, "run_wiki_compile_job", should_not_run)

    result = await wiki_worker.run_wiki_worker_once(worker_id="worker-test", batch_size=2)

    assert result == {"worker_id": "worker-test", "job_ids": [], "processed_count": 0}
