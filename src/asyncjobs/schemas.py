"""API request/response schemas."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class WebhookStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    filename: str | None = None
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] | None = None
    error: str | None = None
    webhook_status: WebhookStatus | None = None


def job_to_response(job: dict[str, str]) -> JobStatusResponse:
    """Build a response model from the raw Redis hash for a job."""
    return JobStatusResponse(
        job_id=job["job_id"],
        status=JobStatus(job["status"]),
        filename=job.get("filename") or None,
        created_at=datetime.fromisoformat(job["created_at"]),
        updated_at=datetime.fromisoformat(job["updated_at"]),
        result=json.loads(job["result"]) if job.get("result") else None,
        error=job.get("error") or None,
        webhook_status=WebhookStatus(job["webhook_status"]) if job.get("webhook_status") else None,
    )
