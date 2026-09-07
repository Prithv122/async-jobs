import asyncio
import uuid

import pytest

from asyncjobs.store import create_job, get_job, reserve_idempotency_key, update_job

pytestmark = pytest.mark.asyncio


async def test_create_and_get_job(redis_client) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="a.txt", webhook_url=None)

    job = await get_job(redis_client, job_id)

    assert job is not None
    assert job["job_id"] == job_id
    assert job["status"] == "pending"
    assert job["filename"] == "a.txt"


async def test_get_job_missing_returns_none(redis_client) -> None:
    assert await get_job(redis_client, "does-not-exist") is None


async def test_update_job_merges_fields_and_bumps_updated_at(redis_client) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename=None, webhook_url=None)
    before = await get_job(redis_client, job_id)

    await update_job(redis_client, job_id, status="running")
    after = await get_job(redis_client, job_id)

    assert after["status"] == "running"
    assert after["filename"] == before["filename"]  # untouched fields survive
    assert after["updated_at"] >= before["updated_at"]
    assert after["created_at"] == before["created_at"]  # created_at never changes


async def test_reserve_idempotency_key_first_caller_owns_it(redis_client) -> None:
    key = uuid.uuid4().hex
    job_id = uuid.uuid4().hex

    result = await reserve_idempotency_key(redis_client, key, job_id, ttl_seconds=60)

    assert result is None  # None means "you own it, go create the job"


async def test_reserve_idempotency_key_second_caller_gets_existing_job_id(redis_client) -> None:
    key = uuid.uuid4().hex
    first_job_id = uuid.uuid4().hex
    second_job_id = uuid.uuid4().hex

    await reserve_idempotency_key(redis_client, key, first_job_id, ttl_seconds=60)
    result = await reserve_idempotency_key(redis_client, key, second_job_id, ttl_seconds=60)

    assert result == first_job_id


async def test_reserve_idempotency_key_is_race_safe(redis_client) -> None:
    """Concurrent reservations for the same key: exactly one caller must win."""
    key = uuid.uuid4().hex
    candidate_ids = [uuid.uuid4().hex for _ in range(10)]

    results = await asyncio.gather(
        *(reserve_idempotency_key(redis_client, key, jid, ttl_seconds=60) for jid in candidate_ids)
    )

    winners = [jid for jid, result in zip(candidate_ids, results, strict=True) if result is None]
    assert len(winners) == 1
    losers_pointed_at_winner = [r for r in results if r is not None]
    assert all(r == winners[0] for r in losers_pointed_at_winner)
