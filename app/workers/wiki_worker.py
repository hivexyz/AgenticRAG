"""Standalone worker for durable Wiki compile jobs."""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import and_, or_, select

from app.config import settings
from app.database.postgres import async_session_maker, postgres_manager
from app.db_models import WikiCompileJob
from app.services.wiki import _utcnow, run_wiki_compile_job
from app.utils.logger import logger


async def find_due_wiki_compile_job_ids(*, limit: Optional[int] = None) -> List[int]:
    batch_size = limit or settings.WIKI_WORKER_BATCH_SIZE
    now = _utcnow()
    stale_before = now - timedelta(seconds=max(settings.WIKI_COMPILE_JOB_STALE_SECONDS, 1))
    async with async_session_maker() as session:
        result = await session.execute(
            select(WikiCompileJob.id)
            .where(
                or_(
                    and_(
                        WikiCompileJob.status == "pending",
                        or_(WikiCompileJob.next_run_at.is_(None), WikiCompileJob.next_run_at <= now),
                    ),
                    and_(
                        WikiCompileJob.status == "processing",
                        or_(WikiCompileJob.locked_at.is_(None), WikiCompileJob.locked_at <= stale_before),
                    ),
                )
            )
            .order_by(WikiCompileJob.created_at.asc(), WikiCompileJob.id.asc())
            .limit(batch_size)
        )
        return [int(job_id) for job_id in result.scalars().all()]


async def run_wiki_worker_once(*, worker_id: Optional[str] = None, batch_size: Optional[int] = None) -> Dict[str, Any]:
    worker_id = worker_id or f"wiki-worker-{uuid4().hex[:12]}"
    job_ids = await find_due_wiki_compile_job_ids(limit=batch_size)
    for job_id in job_ids:
        await run_wiki_compile_job(job_id, worker_id=worker_id)
    return {"worker_id": worker_id, "job_ids": job_ids, "processed_count": len(job_ids)}


async def run_wiki_worker(
    *,
    worker_id: Optional[str] = None,
    poll_seconds: Optional[int] = None,
    batch_size: Optional[int] = None,
    run_once: bool = False,
) -> None:
    worker_id = worker_id or f"wiki-worker-{uuid4().hex[:12]}"
    interval = poll_seconds if poll_seconds is not None else settings.WIKI_WORKER_POLL_SECONDS
    logger.info(f"Wiki worker 启动: worker_id={worker_id}, poll_seconds={interval}")
    try:
        while True:
            result = await run_wiki_worker_once(worker_id=worker_id, batch_size=batch_size)
            if result["processed_count"]:
                logger.info(f"Wiki worker 执行完成: {result}")
            if run_once:
                return
            await asyncio.sleep(max(interval, 1))
    finally:
        await postgres_manager.close_db()
        logger.info(f"Wiki worker 已停止: worker_id={worker_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AgenticRAG Wiki compile worker")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll-seconds", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--once", action="store_true", help="Run one polling iteration and exit")
    args = parser.parse_args()
    asyncio.run(
        run_wiki_worker(
            worker_id=args.worker_id,
            poll_seconds=args.poll_seconds,
            batch_size=args.batch_size,
            run_once=args.once,
        )
    )


if __name__ == "__main__":
    main()
