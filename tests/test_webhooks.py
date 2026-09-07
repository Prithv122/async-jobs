import json
import uuid

import httpx

from asyncjobs.config import settings
from asyncjobs.store import create_job, get_job
from asyncjobs.webhooks import compute_signature, deliver_webhook


def test_compute_signature_is_deterministic_and_keyed() -> None:
    body = b'{"job_id": "abc"}'
    sig1 = compute_signature(body, secret="secret-a")
    sig2 = compute_signature(body, secret="secret-a")
    sig3 = compute_signature(body, secret="secret-b")

    assert sig1 == sig2
    assert sig1 != sig3
    assert len(sig1) == 64  # hex-encoded sha256


async def test_deliver_webhook_success_on_first_attempt(redis_client) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="a.txt", webhook_url="http://example/hook")

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        ok = await deliver_webhook(
            redis_client, job_id, "http://example/hook", {"job_id": job_id}, client=client
        )
    finally:
        await client.aclose()

    assert ok is True
    assert len(calls) == 1
    job = await get_job(redis_client, job_id)
    assert job["webhook_status"] == "delivered"

    body = json.loads(calls[0].content)
    assert body["job_id"] == job_id
    expected_sig = compute_signature(calls[0].content)
    assert calls[0].headers["x-webhook-signature"] == expected_sig


async def test_deliver_webhook_succeeds_after_transient_failure(redis_client) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="a.txt", webhook_url="http://example/hook")

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(500)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        ok = await deliver_webhook(
            redis_client, job_id, "http://example/hook", {"job_id": job_id}, client=client
        )
    finally:
        await client.aclose()

    assert ok is True
    assert attempts["n"] == 2
    job = await get_job(redis_client, job_id)
    assert job["webhook_status"] == "delivered"


async def test_deliver_webhook_handles_connection_errors_and_uses_a_default_client(
    redis_client,
) -> None:
    """No client injected -> deliver_webhook makes its own, and a real connection failure
    (nothing listening on this port) is caught the same way a bad status code is."""
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="a.txt", webhook_url="http://example/hook")

    ok = await deliver_webhook(redis_client, job_id, "http://127.0.0.1:1/hook", {"job_id": job_id})

    assert ok is False
    job = await get_job(redis_client, job_id)
    assert job["webhook_status"] == "failed"


async def test_deliver_webhook_gives_up_after_max_retries(redis_client) -> None:
    job_id = uuid.uuid4().hex
    await create_job(redis_client, job_id, filename="a.txt", webhook_url="http://example/hook")

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        ok = await deliver_webhook(
            redis_client, job_id, "http://example/hook", {"job_id": job_id}, client=client
        )
    finally:
        await client.aclose()

    assert ok is False
    assert attempts["n"] == settings.webhook_max_retries  # bounded, not retried forever
    job = await get_job(redis_client, job_id)
    assert job["webhook_status"] == "failed"
