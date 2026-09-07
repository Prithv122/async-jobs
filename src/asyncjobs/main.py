"""FastAPI app: POST /jobs enqueues work and returns immediately; GET /jobs/{id} polls state.

Scope is deliberately narrow (see GUIDELINES.md): no auth, no database beyond Redis, no
frontend, single-process deployment. The point being demonstrated is the queue
architecture -- upload -> Redis -> worker -> status polling -> webhook -- not a full
job-management product.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from asyncjobs.config import settings
from asyncjobs.schemas import job_to_response
from asyncjobs.store import create_job, get_job, reserve_idempotency_key


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.state_redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield
    finally:
        await app.state.arq_pool.aclose()
        await app.state.state_redis.aclose()


app = FastAPI(title="Async Jobs", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/jobs", status_code=202)
async def create_job_endpoint(
    request: Request,
    file: UploadFile = File(...),
    webhook_url: str | None = Form(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    arq_pool: ArqRedis = request.app.state.arq_pool
    state_redis: Redis = request.app.state.state_redis

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file too large")

    job_id = uuid.uuid4().hex
    owns_job = True

    if idempotency_key:
        existing_job_id = await reserve_idempotency_key(
            state_redis, idempotency_key, job_id, settings.idempotency_key_ttl_seconds
        )
        if existing_job_id is not None:
            job_id = existing_job_id
            owns_job = False

    if owns_job:
        await create_job(state_redis, job_id, filename=file.filename, webhook_url=webhook_url)
        await arq_pool.enqueue_job(
            "process_job", job_id, content, file.filename, webhook_url, _job_id=job_id
        )

    job = await get_job(state_redis, job_id)
    if job is None:  # pragma: no cover - would need Redis to lose the key we just wrote
        raise HTTPException(status_code=500, detail="job vanished immediately after creation")

    response = job_to_response(job)
    headers = {} if owns_job else {"X-Idempotent-Replay": "true"}
    return JSONResponse(
        status_code=202 if owns_job else 200,
        content=response.model_dump(mode="json"),
        headers=headers,
    )


@app.get("/jobs/{job_id}")
async def get_job_endpoint(job_id: str, request: Request) -> JSONResponse:
    state_redis: Redis = request.app.state.state_redis
    job = await get_job(state_redis, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    response = job_to_response(job)
    return JSONResponse(content=response.model_dump(mode="json"))
