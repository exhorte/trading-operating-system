"""Identifier helpers. Ids are opaque strings; the prefix only helps a human reading a log."""

from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """``cmd-3f2a9c1d7b4e`` — 12 hex chars of a random UUID, prefixed."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def new_command_id() -> str:
    """Idempotency key of an execution command (one id ⇒ at most one execution)."""
    return new_id("cmd")
