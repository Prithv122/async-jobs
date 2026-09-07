# Resume Bullets — Async Jobs

Form: **action → technical specifics → measured outcome.** Numbers or it doesn't go on the resume.

---

## Bullets

- Built an async job-processing API (FastAPI + arq + Redis) where `POST /jobs` returns a
  job id in ~13ms while a background worker completes the actual work, verified against a
  real Redis and Docker Compose stack — not a mocked datastore.
- Implemented client-driven idempotency (`Idempotency-Key` header via atomic Redis `SET
  NX`) proven race-safe under 10 concurrent requests for the same key, plus HMAC-signed
  webhook delivery with bounded exponential-backoff retries (5 attempts, then a pollable
  `failed` state instead of retrying forever).
- Reached 100% statement coverage across 32 tests exercising the queue, idempotency, and
  webhook-retry logic against a real Redis in CI (service container), catching a real
  Docker-only bug (a runtime dependency misplaced in the dev-only group) that the local
  test suite alone never surfaced.

## Which roles this supports

- [ ] Data Scientist / ML
- [x] AI Engineer (LLM/NLP/CV)
- [x] Data Engineer
- [x] Data Analyst / Python Developer

_(Marked for AI Engineer / Data Engineer as the general async-processing pattern behind
production ML inference and ETL pipelines; Data Analyst/Python Developer for the FastAPI +
production Python craftsmanship. Not Data Scientist — no modeling in this project.)_

## Keywords this project earns

FastAPI · Redis · arq · task queue · idempotency · webhooks · HMAC signing · exponential
backoff · Docker Compose · pytest-asyncio · async Python · CI service containers.

---

### Bad vs good

❌ "Built a machine learning model to predict customer churn using Python."
✅ "Built a churn classifier on 240k accounts (LightGBM, 1:40 class imbalance) with isotonic calibration and cost-sensitive thresholding, lifting precision@10% from 0.31 to 0.58 over the business's existing rules baseline."

The second one is answerable in an interview. The first invites the question you can't answer.
