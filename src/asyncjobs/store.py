"""Job state and idempotency-key reservations in Redis.

A job is a Redis hash at ``job:{job_id}``. There is no separate database — the API and the
worker both read/write the same hash, so job state has exactly one source of truth.

Idempotency uses a second key, ``idem:{key}``, set with NX (only if absent) so two
concurrent requests for the same ``Idempotency-Key`` race safely: exactly one of them wins
the SETNX and creates the job, the other reads the winner's job id back and never creates
anything of its own (so there is nothing to clean up on the losing side).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis


def _job_key(job_id: str) -> str:
    return f"job:{job_id}"


def _idem_key(key: str) -> str:
    return f"idem:{key}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def create_job(
    redis: Redis,
    job_id: str,
    *,
    filename: str | None,
    webhook_url: str | None,
) -> None:
    now = _now()
    await redis.hset(
        _job_key(job_id),
        mapping={
            "job_id": job_id,
            "status": "pending",
            "filename": filename or "",
            "webhook_url": webhook_url or "",
            "webhook_status": "",
            "result": "",
            "error": "",
            "created_at": now,
            "updated_at": now,
        },
    )


async def get_job(redis: Redis, job_id: str) -> dict[str, str] | None:
    data = await redis.hgetall(_job_key(job_id))
    return data or None


async def update_job(redis: Redis, job_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    await redis.hset(_job_key(job_id), mapping=fields)


async def reserve_idempotency_key(
    redis: Redis,
    key: str,
    job_id: str,
    ttl_seconds: int,
) -> str | None:
    """Try to claim ``key`` for ``job_id``.

    Returns ``None`` if the caller now owns the key (create the job and enqueue it).
    Returns the existing job id if someone else already claimed it (reuse that job).
    """
    created = await redis.set(_idem_key(key), job_id, nx=True, ex=ttl_seconds)
    if created:
        return None
    existing = await redis.get(_idem_key(key))
    return existing
