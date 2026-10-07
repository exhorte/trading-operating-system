"""The trading day and the loss streak.

The broker's trading day starts at **server midnight**, not 00:00 UTC. The offset comes from the MT5 terminal (the
tick clock against the real UTC clock), never hard-coded, since it shifts with DST. Callers re-resolve periodically
so a day rolling over on a long-lived connection is picked up without a fresh handshake.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone

from trading_os.domain.primitives import DomainModel

# Bound on how far back to look for a streak — no real trader runs a losing streak anywhere near this long.
MAX_RECENT_CLOSED_TRADES = 50


def resolve_today_start_utc(utc_now: datetime, server_utc_offset_minutes: int) -> datetime:
    """UTC instant of the current server-day's midnight."""
    server_tz = timezone(timedelta(minutes=server_utc_offset_minutes))
    local_now = utc_now.astimezone(server_tz)
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC)


def estimate_server_utc_offset_minutes(tick_epoch_seconds: float, system_epoch_seconds: float) -> int:
    """MT5 tick timestamps are epoch seconds that represent the broker's *server* time, not true UTC; comparing one
    to the real clock reveals the broker's offset. Rounded to 30 minutes: real offsets are always half-hour aligned
    and the raw difference carries clock drift and latency noise."""
    return round((tick_epoch_seconds - system_epoch_seconds) / 60 / 30) * 30


class StreakTrade(DomainModel):
    realized_pnl: float
    closed_at: datetime


def count_consecutive_losses(most_recent_first: Iterable[StreakTrade]) -> tuple[int, datetime | None]:
    """Trailing run of losses from the most recent trade backwards, stopping at the first non-losing trade.
    The streak never resets at the day anchor (a losing streak spanning midnight is still a streak)."""
    count = 0
    last_loss_at: datetime | None = None
    for trade in most_recent_first:
        if trade.realized_pnl >= 0:
            break
        count += 1
        if last_loss_at is None:
            last_loss_at = trade.closed_at
    return count, last_loss_at
