"""Test-only settings, applied before anything under src/ is imported.

Tests run against a real Redis (database 15, kept separate from the dev default of 0) --
same "no mocking the thing the project is about" discipline as the other catalog projects.
Simulated work time and webhook backoff are both cut to milliseconds so the suite stays fast
without changing any of the logic being tested.
"""

import os

import pytest_asyncio
from redis.asyncio import Redis

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("SIMULATED_WORK_SECONDS", "0.05")
os.environ.setdefault("WEBHOOK_BACKOFF_BASE_SECONDS", "0.01")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")

from asyncjobs.config import settings


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()
