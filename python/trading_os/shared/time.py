"""Time: every timestamp in the core is timezone-aware UTC. Clocks are injectable so rules are testable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    """ISO 8601 with a ``Z`` suffix and millisecond precision (what the cockpit's store expects)."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime: timestamps must be timezone-aware UTC")
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` or offset) into an aware UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without a timezone: {value!r}")
    return parsed.astimezone(UTC)


def from_epoch_ms(ms: int | float) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def to_epoch_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utcnow()


class ManualClock:
    """A clock tests move by hand."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> datetime:
        self._now = self._now + timedelta(**kwargs)
        return self._now

    def set(self, value: datetime) -> None:
        self._now = value
