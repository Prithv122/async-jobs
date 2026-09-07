"""The arq worker: consumes queued jobs from Redis and does the actual work.

Uses its own Redis connection (``ctx["state_redis"]``, decode_responses=True) for job-state
reads/writes, separate from arq's own bookkeeping connection (``ctx["redis"]``) -- arq's
connection is bytes-mode and only used internally by arq itself.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, ClassVar

from arq.connections import RedisSettings
from redis.asyncio import Redis

from asyncjobs.config import settings
from asyncjobs.processing import analyze_content
from asyncjobs.store import get_job, update_job
from asyncjobs.webhooks import deliver_webhook


async def process_job(
    ctx: dict[str, Any],
    job_id: str,
    content: bytes,
    filename: str | None,
    webhook_url: str | None,
) -> dict[str, Any]:
    state_redis: Redis = ctx["state_redis"]

    await update_job(state_redis, job_id, status="running")
    try:
        result = analyze_content(content)
        # Simulated processing time: proves the API returned before this ran, not after.
        await asyncio.sleep(settings.simulated_work_seconds)
        await update_job(state_redis, job_id, status="done", result=json.dumps(result))
    except Exception as exc:
        result = {"error": str(exc)}
        await update_job(state_redis, job_id, status="failed", error=str(exc))

    if webhook_url:
        await update_job(state_redis, job_id, webhook_status="pending")
        job = await get_job(state_redis, job_id)
        if job is not None:
            await deliver_webhook(state_redis, job_id, webhook_url, job)

    return result


async def on_startup(ctx: dict[str, Any]) -> None:
    ctx["state_redis"] = Redis.from_url(settings.redis_url, decode_responses=True)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await ctx["state_redis"].aclose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [process_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = on_startup
    on_shutdown = on_shutdown
