# Interview Prep — Async Jobs

**Five questions, five answers.** An unanswered question means this project is not shipped.

If you can't answer one, you don't understand that part of your own project yet — go back and understand it. This file is the difference between a portfolio that survives a technical screen and one that collapses in it.

---

### Q1. Walk me through the architecture in 90 seconds.

_A:_ A client `POST`s a file to `/jobs`. FastAPI reads it into memory, writes a Redis hash
recording the job as `pending`, enqueues an arq task with the file bytes as an argument, and
returns the job id — all before any actual processing happens. Redis is doing two separate
jobs here: it's arq's message broker (the queue itself) *and* the single source of truth for
job state, so the API and the worker never talk to each other directly — they only ever talk
to Redis. Separately, an arq worker process is polling that same Redis for jobs; when one
arrives, it flips status to `running`, does the analysis (checksum, byte/word/line counts),
writes `done` plus the result, and — if a webhook URL was given — POSTs a signed payload to
it with retries. The client polls `GET /jobs/{id}` at any point and just reads that same
Redis hash back through the API.

### Q2. Why did you choose a Redis hash for job state instead of a database?

_A:_ Because the catalog scope for this project is specifically the queue architecture —
idempotency, long-running work, status polling — not "build another CRUD API with a
database," which C2 already covers. Redis was already required as arq's broker, so using it
for job state too meant there's exactly one moving part to reason about, and `SET NX` gives
me atomic idempotency reservations for free, which a second database wouldn't. The tradeoff
I'm explicit about in the README: this doesn't scale to durable job history past Redis's own
retention, and at real scale I'd add a Postgres table the worker writes to for that reason —
but for this project's actual point, one datastore is the right call, not a shortcut.

### Q3. What's the weakest part of this, and what would break first under load?

_A:_ Webhook delivery has no dead-letter path. Right now, if a webhook receiver is
permanently gone, delivery retries five times with exponential backoff and then just sits at
`webhook_status: failed` — the client only finds out by polling. At real volume that's a
silent failure mode: nobody gets paged, nothing accumulates anywhere queryable. The fix is
either a dead-letter queue or an alerting hook on the failed-delivery rate, and I called that
out explicitly in the README rather than pretending it's handled. Separately, uploaded file
content is passed to the worker as a raw argument through arq's own serialization — fine at
the 10MB cap I enforce, but that cap exists precisely because pickling a much larger payload
through Redis would be the wrong design; a real large-file pipeline would have the API write
to object storage and pass the worker a reference, not the bytes themselves.

### Q4. How do you know it works? What did you measure, and against what baseline?

_A:_ Every claim in the README's Results table comes from `scripts/demo.py`, which runs the
real FastAPI app against a real arq worker and a real Redis — nothing mocked — and prints
exactly those numbers: `POST /jobs` returning in ~13ms while the worker takes the full
configured 2 seconds to actually finish the job proves the API isn't blocking on the work.
A batch of 5 jobs finishing in ~2.08s against a naive sequential estimate of 10s (4.8×) is
measured worker concurrency, not an assumed number. Idempotency is tested both at the API
level (same key → same job id, second response is 200 not 202) and adversarially — 10
concurrent reservation attempts for the same key in `test_store.py`, asserting exactly one
winner, because idempotency that isn't safe under a real race isn't idempotency. And the
whole stack (API + worker + Redis) was actually run through `docker compose up`, not just
`pytest` — that's how I caught that `httpx` was missing from the worker container in the
first place (see Q5).

### Q5. What's a real bug you hit building this, not just "tests passed on the first try"?

_A:_ `httpx` was only in the dev dependency group, since it's used in tests and I initially
thought of it as test tooling. `pytest` was green the whole time it was misplaced — the dev
venv has both dependency groups installed, so nothing local ever caught it. It was only when
I actually ran `docker compose up --build` (the Dockerfile installs with `--no-dev`) that the
worker container crashed on startup with `ModuleNotFoundError: No module named 'httpx'` —
because `webhooks.py` genuinely needs `httpx` at runtime to deliver webhook callbacks, not
just in tests. Fixed by moving it into real `[project.dependencies]`. The lesson that stuck:
"tests pass" only proves the dev environment's dependencies are sufficient; for a project
that ships its own Dockerfile, the container build is the real acceptance test for what's a
runtime dependency versus a dev-only one, and I hadn't actually run it until I went looking
for real numbers for the README.

---

## 30-second pitch

Async Jobs is a FastAPI + arq + Redis service that demonstrates the core queue-architecture
pattern behind any "upload now, process later" system: `POST /jobs` returns a job id in
~13ms without blocking on the work, an arq worker does the actual processing out-of-band
against the same Redis, `GET /jobs/{id}` polls status, and a signed webhook fires on
completion with bounded exponential-backoff retries. Idempotency is client-driven via an
`Idempotency-Key` header, proven safe under 10 concurrent requests for the same key in
tests. Every number in the README — the 13ms enqueue latency, the 4.8× concurrency speedup
on a 5-job batch, the webhook retry timing — comes from `scripts/demo.py` running the real
stack, not a mock.
