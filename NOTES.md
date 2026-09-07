# Build Notes — Async Jobs

Working notes: what broke, what you tried, why you chose X over Y.
Not for recruiters — for you, six months from now, in an interview.

---

## Log

### 2026-09-07
- **Tried:** `httpx` only in the `dev` dependency-group (it's used by tests and by
  `webhooks.py` for delivering the actual callback).
- **Broke:** `docker compose up --build` built clean, but the **worker** container crashed
  on startup with `ModuleNotFoundError: No module named 'httpx'`. The API container was
  fine — nothing in `main.py` imports `httpx` directly — but `worker.py` imports
  `webhooks.py`, which does, and the Dockerfile builds with `uv sync --frozen --no-dev`, so
  dev-only deps never make it into the image.
- **Fixed by:** moving `httpx` into `[project.dependencies]` (it's genuinely a runtime
  dependency — the worker calls out to arbitrary webhook URLs — not just a test tool).
  Caught by actually running `docker compose up` and checking `docker logs`, not by trusting
  `pytest` green (tests run inside the dev venv, which has both groups installed, so this
  gap is invisible from the test suite alone).
- **Learned:** "tests pass" only proves the dev environment's dependency set is sufficient.
  For a project shipping its own Dockerfile, the container build *is* the real acceptance
  test for `dependencies` vs. `dependency-groups.dev` — run it before calling anything done.

- **Tried:** running an in-process arq `Worker` from `scripts/demo.py` (needed to produce
  real timing numbers without requiring two extra terminals for `uvicorn` + `arq worker`).
- **Broke:** `worker.close()` raised `AttributeError: module 'signal' has no attribute
  'SIGUSR1'` on shutdown, even with `handle_signals=False` passed to the constructor. arq's
  `Worker.close()` unconditionally does `self.handle_sig(signal.SIGUSR1)` as part of its own
  internal bookkeeping (cancelling in-flight tasks, logging a summary) regardless of whether
  the worker is managing OS signal handlers itself — and `SIGUSR1` doesn't exist in Python's
  `signal` module on Windows.
- **Fixed by:** a one-line shim before constructing the worker:
  `if not hasattr(signal, "SIGUSR1"): signal.SIGUSR1 = signal.SIGTERM`. It only needs to be
  a valid `Signals` enum member for `handle_sig`'s logging/cancellation path — the value
  itself is never delivered as a real signal in this code path.
- **Learned:** arq's Windows support has a real gap in its shutdown path, not just in signal
  *registration* (which `handle_signals=False` already sidesteps) — worth remembering if
  `docker compose`'s worker service (Linux container, no shim needed) ever needs a Windows
  bare-metal equivalent.

- **Tried:** unit tests for the arq worker's `process_job` calling it directly with a bare
  `ctx = {"state_redis": redis_client}`, without first calling `create_job()`.
- **Broke:** `KeyError: 'error'` / `KeyError: 'webhook_status'` reading the job hash back.
  `update_job()` only `HSET`s the fields it's given — on a hash that doesn't exist yet, that
  means the hash ends up with *only* those fields, not the full set `create_job()` normally
  seeds (`error`, `webhook_status`, etc. as empty strings). In real usage the API always
  calls `create_job()` before enqueueing, so this ordering is never actually violated — the
  bug was in the test's setup, not in `worker.py`.
- **Fixed by:** calling `create_job()` first in every `test_worker.py` test, matching the
  real call sequence (API creates the hash → enqueues → worker updates it).
- **Learned:** when a "unit" test skips a step the real caller always performs, a passing
  assertion two functions apart can hide the fact that the test's own setup was unrealistic
  rather than confirming real behavior.

- **Tried:** a hardcoded `Idempotency-Key` value (`"retry-key-1"`) in
  `test_idempotency_key_reuses_the_same_job`.
- **Broke:** passed on first run, failed on the *second* run of the same test file (`assert
  first.status_code == 202` got `200` instead). The test suite runs against a real Redis
  (per-project convention: no mocking the thing being tested), and idempotency keys are
  intentionally durable (24h TTL) — so a hardcoded key collides with whatever the *previous*
  test run already wrote for that key.
- **Fixed by:** generating a fresh `uuid.uuid4().hex` key per test invocation, same pattern
  already used in `test_store.py`. Same fix applied to `scripts/demo.py`'s idempotency demo
  section, which had the identical bug for the identical reason.
- **Learned:** testing against a *real*, *not-flushed-between-runs* datastore means any
  test-authored key needs to be unique per run, not just per test-within-a-run — otherwise
  "run the suite twice in a row" (a real regression check, not paranoia) silently breaks.

---

## Rejected approaches

| Approach | Why rejected |
|---|---|
| Store job state in a separate Postgres/SQLite table alongside Redis | The catalog scope for C3 is specifically the queue architecture (Redis as broker *and* state store) — a second database would add a moving part the project isn't about, and duplicate Redis's own atomicity guarantees (SETNX for idempotency) for no benefit. |
| Mock `httpx` for all webhook tests | Used `httpx.MockTransport` for the *destination* server (the thing our webhook is calling), which is standard practice and not the same as mocking the datastore. The one thing genuinely worth testing against reality — a real connection refusal — is covered separately with an actual unreachable port. |
| Use arq's own `_job_id`-based dedup as the *only* idempotency mechanism | arq's per-job-id dedup exists and is passed as a secondary safety net (`_job_id=job_id` on `enqueue_job`), but it's not client-facing (a client doesn't choose arq's internal job id) and its "already exists" window is tied to arq's own result-retention window, not something a client can reason about. The explicit `Idempotency-Key` header is the one deliberately designed per the spec — client-supplied, TTL clearly owned by this project's own config. |
| Run the demo's arq `Worker` via `arq.worker.run_worker()` (arq's own CLI-style entrypoint) | `run_worker` blocks the calling thread until a shutdown signal, which doesn't compose with `scripts/demo.py` wanting to run a worker *and* drive HTTP requests *and* print results from one script. Built the worker directly from the `Worker` class in a background thread instead. |

## Open questions

- [ ] At real scale, `analyze_content()`'s work (hashing + text stats) is cheap enough that
      the 2-second `simulated_work_seconds` default is doing all the "long-running work"
      demonstration — a real deployment would swap this for actual expensive work (image
      transforms, PDF extraction, etc.) without touching the queue/status/webhook plumbing
      around it. Worth calling out explicitly in the README rather than implying the analysis
      itself is the point.
