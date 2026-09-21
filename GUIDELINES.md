# Async Jobs — C3

**Tier:** 2 · **Category:** C — Python web · **Wave:** 3 — Production tier

Root rules in `../GUIDELINES.md` apply. This file is project-specific only — keep it under 40 lines.

## What this is

Upload → background worker (arq/Redis) → status polling + webhooks.

## Stack

FastAPI (upload/status API) + arq (Redis-backed async task queue) + Redis (broker) +
pytest/httpx + Docker Compose (app + worker + Redis).

## Acceptance criteria

- [x] Upload endpoint enqueues a background job (arq worker, Redis-backed)
- [x] Job status is pollable (pending/running/done/failed) with idempotent enqueue
- [x] Completion triggers a webhook callback
- [x] Long-running work handled without blocking the API (queues, not threads)
- [x] Ship gate passes

## Project-specific notes

- **Needs Redis.** `docker compose up --build` starts Redis + API + worker together —
  verified end-to-end for real (built images, hit `/jobs` over HTTP, watched
  pending→running→done, confirmed webhook retry-then-`failed` against an unreachable port).
- Idempotency key: client-supplied `Idempotency-Key` header, claimed via Redis `SET NX`.
  Webhook retry: bounded exponential backoff (5 attempts, 1s base), then `failed` — never
  retried forever. Both are the design core here; see README §4 for the reasoning.
- Real bug worth remembering: `httpx` must be a runtime dependency (the worker's own
  `webhooks.py` imports it), not dev-only — a dev-only placement passes `pytest` locally but
  crashes the Docker Compose `worker` service, which installs with `--no-dev`. See NOTES.md.
