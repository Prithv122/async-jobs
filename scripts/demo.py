"""Runs the real API against a real arq worker (both talking to a real Redis) and prints
timing numbers -- the source for the README's "Results" section. Nothing here is mocked;
every number printed is measured, not guessed.

Requires Redis reachable at REDIS_URL (default redis://localhost:6379/0). Run with:

    uv run python scripts/demo.py
"""

from __future__ import annotations

import asyncio
import json
import signal
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

from arq.worker import Worker
from fastapi.testclient import TestClient

from asyncjobs.config import settings
from asyncjobs.main import app
from asyncjobs.webhooks import compute_signature
from asyncjobs.worker import WorkerSettings

# arq's Worker.close() unconditionally reads signal.SIGUSR1 as part of its own internal
# shutdown bookkeeping, even when handle_signals=False -- SIGUSR1 doesn't exist on Windows,
# so close() crashes with AttributeError there. Not a bug in our code; documented in NOTES.md.
if not hasattr(signal, "SIGUSR1"):
    signal.SIGUSR1 = signal.SIGTERM

SAMPLE_TEXT = ("the quick brown fox jumps over the lazy dog\n" * 200).encode()


def _run_worker_in_background(stop_event: threading.Event) -> None:
    async def _run() -> None:
        worker = Worker(
            functions=WorkerSettings.functions,
            redis_settings=WorkerSettings.redis_settings,
            on_startup=WorkerSettings.on_startup,
            on_shutdown=WorkerSettings.on_shutdown,
            handle_signals=False,  # arq's default signal handling isn't available on Windows
            poll_delay=0.05,
        )
        run_task = asyncio.ensure_future(worker.async_run())
        try:
            while not stop_event.is_set():
                await asyncio.sleep(0.1)
        finally:
            run_task.cancel()
            await worker.close()

    asyncio.run(_run())


def _post_job(client: TestClient, webhook_url: str | None = None) -> tuple[str, float]:
    started = time.perf_counter()
    data = {"webhook_url": webhook_url} if webhook_url else {}
    response = client.post(
        "/jobs", files={"file": ("sample.txt", SAMPLE_TEXT, "text/plain")}, data=data
    )
    latency = time.perf_counter() - started
    response.raise_for_status()
    return response.json()["job_id"], latency


def _wait_for_completion(client: TestClient, job_id: str) -> float:
    started = time.perf_counter()
    while True:
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return time.perf_counter() - started
        time.sleep(0.02)


class _WebhookReceiver(BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[bytes, dict]]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        _WebhookReceiver.received.append((body, dict(self.headers)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:  # silence stdlib's default request logging
        pass


def main() -> None:
    print(f"Redis: {settings.redis_url}")
    print(f"Simulated worker processing time per job: {settings.simulated_work_seconds}s\n")

    stop_event = threading.Event()
    worker_thread = threading.Thread(
        target=_run_worker_in_background, args=(stop_event,), daemon=True
    )
    worker_thread.start()
    time.sleep(0.5)  # let the worker connect before sending jobs

    try:
        with TestClient(app) as client:
            # 1. A single job: how fast does POST /jobs return vs. how long until it's done.
            job_id, enqueue_latency = _post_job(client)
            completion_latency = _wait_for_completion(client, job_id)
            result = client.get(f"/jobs/{job_id}").json()["result"]

            print("Single job:")
            print(f"  POST /jobs response time:        {enqueue_latency * 1000:6.1f} ms")
            print(f"  Time until status = done:         {completion_latency:6.2f} s")
            print(f"  Analyzed result: {result}\n")

            # 2. Concurrency: N jobs enqueued back-to-back, all processed by one worker
            #    (max_jobs=10 default) roughly in parallel rather than N * simulated-work-time.
            n = 5
            batch_started = time.perf_counter()
            job_ids = [_post_job(client)[0] for _ in range(n)]
            batch_enqueue_elapsed = time.perf_counter() - batch_started

            batch_wait_started = time.perf_counter()
            for jid in job_ids:
                _wait_for_completion(client, jid)
            batch_total_elapsed = time.perf_counter() - batch_wait_started

            sequential_estimate = n * settings.simulated_work_seconds
            print(f"Batch of {n} jobs:")
            print(f"  Total time to enqueue all {n}:     {batch_enqueue_elapsed * 1000:6.1f} ms")
            print(f"  Total time until all {n} done:     {batch_total_elapsed:6.2f} s")
            print(f"  Naive sequential estimate:         {sequential_estimate:6.2f} s")
            speedup = sequential_estimate / batch_total_elapsed
            print(f"  Speedup from worker concurrency:   {speedup:5.2f}x")

            # 3. Idempotency: same Idempotency-Key -> same job, no duplicate enqueue.
            key = f"demo-idempotency-key-{uuid.uuid4().hex[:8]}"
            first_id, _ = _post_job(client)
            resp_a = client.post(
                "/jobs",
                files={"file": ("sample.txt", SAMPLE_TEXT, "text/plain")},
                headers={"Idempotency-Key": key},
            )
            resp_b = client.post(
                "/jobs",
                files={"file": ("sample.txt", SAMPLE_TEXT, "text/plain")},
                headers={"Idempotency-Key": key},
            )
            print("\nIdempotency-Key reuse:")
            print(f"  First request:  {resp_a.status_code} job_id={resp_a.json()['job_id']}")
            print(f"  Second request: {resp_b.status_code} job_id={resp_b.json()['job_id']}")
            print(f"  Same job both times: {resp_a.json()['job_id'] == resp_b.json()['job_id']}")
            assert first_id != resp_a.json()["job_id"], "sanity: unrelated jobs stay distinct"

            # 4. Webhook delivery: a real local HTTP server receives the signed callback.
            server = HTTPServer(("127.0.0.1", 0), _WebhookReceiver)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            webhook_url = f"http://127.0.0.1:{server.server_port}/hook"

            _WebhookReceiver.received.clear()
            webhook_job_id, _ = _post_job(client, webhook_url=webhook_url)
            _wait_for_completion(client, webhook_job_id)

            deadline = time.perf_counter() + 5
            while not _WebhookReceiver.received and time.perf_counter() < deadline:
                time.sleep(0.05)

            server.shutdown()
            server_thread.join(timeout=5)

            print("\nWebhook delivery:")
            if _WebhookReceiver.received:
                body, headers = _WebhookReceiver.received[0]
                payload = json.loads(body)
                expected_sig = compute_signature(body)
                print(f"  Received job payload for: {payload['job_id']}")
                print(
                    f"  Signature header present and valid: "
                    f"{headers.get('X-Webhook-Signature') == expected_sig}"
                )
                # The receiver getting the POST and the worker recording "delivered" happen
                # in that order but aren't instantaneous -- give the update a moment to land.
                webhook_status_deadline = time.perf_counter() + 2
                final_status = None
                while time.perf_counter() < webhook_status_deadline:
                    final_status = client.get(f"/jobs/{webhook_job_id}").json()["webhook_status"]
                    if final_status in ("delivered", "failed"):
                        break
                    time.sleep(0.05)
                print(f"  Job's own webhook_status field:     {final_status}")
            else:
                print("  No webhook received within 5s (unexpected).")
    finally:
        stop_event.set()
        worker_thread.join(timeout=5)


if __name__ == "__main__":
    main()
