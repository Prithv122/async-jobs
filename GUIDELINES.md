# Async Jobs — C3

**Tier:** 2 · **Category:** C — Python web · **Wave:** 3 — Production tier

Root rules in `../GUIDELINES.md` apply. This file is project-specific only — keep it under 40 lines.

## What this is

Upload → background worker (arq/Redis) → status polling + webhooks.

## Stack

FastAPI (upload/status API) + arq (Redis-backed async task queue) + Redis (broker) +
pytest/httpx + Docker Compose (app + worker + Redis).

## Acceptance criteria

- [ ] Upload endpoint enqueues a background job (arq worker, Redis-backed)
- [ ] Job status is pollable (pending/running/done/failed) with idempotent enqueue
- [ ] Completion triggers a webhook callback
- [ ] Long-running work handled without blocking the API (queues, not threads)
- [ ] Ship gate passes (`/ship`)

## Project-specific notes

- **Needs Redis.** Local dev: `docker compose up -d` (once the compose file exists) starts
  Redis + worker alongside the API. Verified this session: Docker Desktop running, a throwaway
  `redis:7-alpine` container responded to `PING` — no separate Redis install needed.
- Idempotency and retry behavior are the design core here (see CATALOG.md "Proves" column) —
  don't let the happy path be the only tested path.
