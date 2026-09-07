"""Webhook delivery: HMAC-signed payload, bounded retries with exponential backoff.

After `settings.webhook_max_retries` attempts, delivery is marked "failed" in the job's
Redis state rather than retried forever -- a webhook receiver that's down should not leave
a worker slot blocked indefinitely.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any

import httpx
from redis.asyncio import Redis

from asyncjobs.config import settings
from asyncjobs.store import update_job


def compute_signature(body: bytes, secret: str | None = None) -> str:
    key = (secret or settings.webhook_secret).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


async def deliver_webhook(
    redis: Redis,
    job_id: str,
    webhook_url: str,
    payload: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """POST payload to webhook_url, retrying with exponential backoff. Returns True on success."""
    body = json.dumps(payload, default=str).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": compute_signature(body),
    }

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=5.0)
    delay = settings.webhook_backoff_base_seconds
    try:
        for attempt in range(1, settings.webhook_max_retries + 1):
            try:
                response = await http_client.post(webhook_url, content=body, headers=headers)
                if response.status_code < 300:
                    await update_job(redis, job_id, webhook_status="delivered")
                    return True
            except httpx.HTTPError:
                pass

            if attempt < settings.webhook_max_retries:
                await asyncio.sleep(delay)
                delay *= 2

        await update_job(redis, job_id, webhook_status="failed")
        return False
    finally:
        if owns_client:
            await http_client.aclose()
