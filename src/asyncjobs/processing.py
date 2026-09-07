"""The actual work a job does. Pure function, no Redis/HTTP — easy to unit test in isolation."""

from __future__ import annotations

import hashlib
from typing import Any


def analyze_content(content: bytes) -> dict[str, Any]:
    """Analyze an uploaded file: size, checksum, and text stats if it decodes as UTF-8."""
    result: dict[str, Any] = {
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        result["is_text"] = False
        return result

    result["is_text"] = True
    result["line_count"] = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    result["word_count"] = len(text.split())
    result["char_count"] = len(text)
    return result
