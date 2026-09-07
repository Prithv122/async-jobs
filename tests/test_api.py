"""API-level tests. No arq worker process runs during these tests, which is the point:
POST /jobs must return before any work happens, and the job simply stays "pending" until a
worker picks it up (proven separately in test_worker.py).
"""

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from asyncjobs.config import settings
from asyncjobs.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_create_job_returns_immediately_with_pending_status(client) -> None:
    started = time.perf_counter()
    response = client.post("/jobs", files={"file": ("notes.txt", b"hello world", "text/plain")})
    elapsed = time.perf_counter() - started

    assert response.status_code == 202
    # No worker is running in this test process, so a fast response proves the API itself
    # doesn't block on the work -- it enqueues and returns.
    assert elapsed < 1.0

    body = response.json()
    assert body["status"] == "pending"
    assert body["filename"] == "notes.txt"
    assert "job_id" in body


def test_get_job_reflects_created_job(client) -> None:
    create_response = client.post("/jobs", files={"file": ("a.txt", b"content", "text/plain")})
    job_id = create_response.json()["job_id"]

    get_response = client.get(f"/jobs/{job_id}")

    assert get_response.status_code == 200
    assert get_response.json()["job_id"] == job_id
    assert get_response.json()["status"] == "pending"


def test_get_unknown_job_is_404(client) -> None:
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404


def test_idempotency_key_reuses_the_same_job(client) -> None:
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    files = {"file": ("a.txt", b"content", "text/plain")}

    first = client.post("/jobs", files=files, headers=headers)
    second = client.post("/jobs", files=files, headers=headers)

    assert first.status_code == 202
    assert "X-Idempotent-Replay" not in first.headers

    assert second.status_code == 200
    assert second.headers["X-Idempotent-Replay"] == "true"
    assert second.json()["job_id"] == first.json()["job_id"]


def test_different_idempotency_keys_create_different_jobs(client) -> None:
    files = {"file": ("a.txt", b"content", "text/plain")}

    first = client.post("/jobs", files=files, headers={"Idempotency-Key": uuid.uuid4().hex})
    second = client.post("/jobs", files=files, headers={"Idempotency-Key": uuid.uuid4().hex})

    assert first.json()["job_id"] != second.json()["job_id"]


def test_no_idempotency_key_always_creates_a_new_job(client) -> None:
    files = {"file": ("a.txt", b"content", "text/plain")}

    first = client.post("/jobs", files=files)
    second = client.post("/jobs", files=files)

    assert first.json()["job_id"] != second.json()["job_id"]


def test_upload_over_the_size_limit_is_rejected(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_bytes", 4)

    response = client.post("/jobs", files={"file": ("big.txt", b"this is too big", "text/plain")})

    assert response.status_code == 413


def test_health_endpoint(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
