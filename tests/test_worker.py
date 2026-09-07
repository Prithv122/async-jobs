"""Tests the worker's task function directly -- the real function arq calls, just invoked
without a running arq worker process. Webhook delivery itself is covered in test_webhooks.py;
here we only check the worker wires it up correctly.
"""

import time
import uuid

import pytest

from asyncjobs import worker as worker_module
from asyncjobs.config import settings
from asyncjobs.store import create_job, get_job
from asyncjobs.worker import on_shutdown, on_startup, process_job

pytestmark = pytest.mark.asyncio


async def test_on_startup_and_shutdown_manage_the_state_redis_connection() -> None:
    ctx: dict = {}

    await on_startup(ctx)
    assert "state_redis" in ctx
    assert await ctx["state_redis"].ping() is True

    await on_shutdown(ctx)


async def test_process_job_happy_path_updates_status_and_result(redis_client) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="notes.txt", webhook_url=None)
    ctx = {"state_redis": redis_client}
    content = b"hello world\nsecond line"

    started = time.perf_counter()
    await process_job(ctx, job_id, content, "notes.txt", None)
    elapsed = time.perf_counter() - started

    # Proves the worker actually does the simulated work rather than completing instantly.
    assert elapsed >= settings.simulated_work_seconds

    job = await get_job(redis_client, job_id)
    assert job["status"] == "done"
    assert job["error"] == ""
    assert '"word_count": 4' in job["result"]


async def test_process_job_failure_marks_job_failed(redis_client, monkeypatch) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="f.txt", webhook_url=None)
    ctx = {"state_redis": redis_client}

    def boom(_content: bytes) -> dict:
        raise ValueError("simulated processing failure")

    monkeypatch.setattr(worker_module, "analyze_content", boom)

    await process_job(ctx, job_id, b"anything", "f.txt", None)

    job = await get_job(redis_client, job_id)
    assert job["status"] == "failed"
    assert "simulated processing failure" in job["error"]


async def test_process_job_triggers_webhook_when_url_given(redis_client, monkeypatch) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="f.txt", webhook_url="http://example/hook")
    ctx = {"state_redis": redis_client}
    calls = []

    async def fake_deliver_webhook(redis, jid, url, payload, **kwargs):
        calls.append((jid, url, payload["status"]))
        return True

    monkeypatch.setattr(worker_module, "deliver_webhook", fake_deliver_webhook)

    await process_job(ctx, job_id, b"hello", "f.txt", "http://example/hook")

    assert len(calls) == 1
    called_job_id, called_url, called_status = calls[0]
    assert called_job_id == job_id
    assert called_url == "http://example/hook"
    assert called_status == "done"


async def test_process_job_without_webhook_url_skips_delivery(redis_client, monkeypatch) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="f.txt", webhook_url=None)
    ctx = {"state_redis": redis_client}

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("deliver_webhook should not be called when webhook_url is None")

    monkeypatch.setattr(worker_module, "deliver_webhook", fail_if_called)

    await process_job(ctx, job_id, b"hello", "f.txt", None)

    job = await get_job(redis_client, job_id)
    assert job["status"] == "done"
    assert job["webhook_status"] == ""
