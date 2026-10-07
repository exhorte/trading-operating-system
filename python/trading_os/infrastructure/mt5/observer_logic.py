"""Pure logic of the former Python observer (``tools/mt5-observer/mt5_observer.py``), kept because it encodes hard-won
facts about MT5 — and fixed where the audit found it wrong.

* A position is keyed by ``POSITION_IDENTIFIER`` (``TradePosition.identifier`` / ``TradeDeal.position_id``), **never** by
  ``ticket``: the identifier does not change for the life of a position, the ticket can be rewritten by broker-side
  service operations. They coincide almost always, which is exactly what made the bug invisible.
* A position can close in several partial deals: its outcome is the **sum** of profit + commission + swap over every deal,
  never one deal alone (a last partial exit can be slightly negative after swap on a net winner).
* A position that opens **and** closes between two polls never appears in the live list: it is reconstructed from the deal
  history of the scan window (« missed round trips »). They are exactly the trades that matter most for discipline metrics.
* **Server time is not UTC.** MT5 timestamps are epoch seconds in the *broker's* clock. The old observer used them as UTC —
  harmless on Exness (GMT+0), wrong by 2–3 h on FTMO (CE(S)T). Everything here converts through the measured server offset,
  and the offset is only measured from a **fresh** tick: on a weekend the last tick is days old and the difference with the
  real clock is not an offset (the old estimate returned garbage then).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from trading_os.domain.primitives import DomainModel, Side
from trading_os.shared.time import from_epoch_ms

DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1

# A real broker offset is within ±14 h; a tick older than this is not a measurement of the clock.
MAX_PLAUSIBLE_OFFSET_MINUTES = 14 * 60 + 30


class Deal(DomainModel):
    """The fields of an MT5 deal the core uses. ``time`` is the broker's clock in epoch seconds."""

    ticket: int = 0
    time: int
    type: int
    entry: int
    position_id: int
    volume: float
    price: float
    commission: float = 0.0
    swap: float = 0.0
    profit: float = 0.0
    symbol: str = ""
    magic: int = 0
    comment: str = ""


class OpenedFact(DomainModel):
    position_id: str
    symbol: str
    side: Side
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    reconstructed: bool = False  # built from deal history alone: stop/target are unknown (0.0)


class ClosedFact(DomainModel):
    position_id: str
    symbol: str
    side: Side
    volume: float
    realized_pnl: float
    exit_price: float
    closed_at: datetime


def server_time_to_utc(server_epoch_seconds: float, offset_minutes: int) -> datetime:
    """The broker's clock reading → a true UTC instant."""
    return from_epoch_ms((server_epoch_seconds - offset_minutes * 60) * 1000)


def utc_to_server_epoch(utc: datetime, offset_minutes: int) -> int:
    """A true UTC instant → the broker-clock epoch seconds MT5's history functions expect."""
    return int(utc.timestamp()) + offset_minutes * 60


def measure_server_offset_minutes(tick_epoch_seconds: float, system_epoch_seconds: float) -> int | None:
    """Offset of the broker's clock from UTC, in minutes, rounded to the half hour (real offsets are always half-hour
    aligned; the raw difference carries drift and latency). ``None`` when the tick is too old to measure anything."""
    minutes = (tick_epoch_seconds - system_epoch_seconds) / 60
    rounded = round(minutes / 30) * 30
    if abs(minutes) > MAX_PLAUSIBLE_OFFSET_MINUTES or abs(rounded) > MAX_PLAUSIBLE_OFFSET_MINUTES:
        return None
    return int(rounded)


def side_of_deal(deal: Deal) -> Side:
    return Side.BUY if deal.type == DEAL_TYPE_BUY else Side.SELL


def diff_position_ids(known: set[str], current: set[str]) -> tuple[set[str], set[str]]:
    """(opened, closed) from one before/after comparison. Deliberately does not special-case an empty ``known``: the
    caller decides whether a poll is a real diff or a baseline-seeding read."""
    return current - known, known - current


def sum_realized_pnl(deals: Iterable[Deal]) -> float:
    return round(sum(d.profit + d.commission + d.swap for d in deals), 2)


def weighted_exit_price(exit_deals: Sequence[Deal]) -> float:
    """Volume-weighted average fill across every exit deal (a partial close in several fills has no single price)."""
    total = sum(d.volume for d in exit_deals)
    if total <= 0:
        return exit_deals[0].price if exit_deals else 0.0
    return round(sum(d.price * d.volume for d in exit_deals) / total, 5)


def closed_fact(position_id: int | str, deals: Sequence[Deal], offset_minutes: int) -> ClosedFact | None:
    """``None`` when the deal history is incomplete (an entry without an exit, or the reverse — a disconnect racing the
    close): never emit a half-known fact."""
    entries = [d for d in deals if d.entry == DEAL_ENTRY_IN]
    exits = [d for d in deals if d.entry == DEAL_ENTRY_OUT]
    if not entries or not exits:
        return None
    first = entries[0]
    return ClosedFact(
        position_id=str(position_id),
        symbol=first.symbol,
        side=side_of_deal(first),
        volume=round(sum(d.volume for d in entries), 2),
        realized_pnl=sum_realized_pnl(deals),
        exit_price=weighted_exit_price(exits),
        closed_at=server_time_to_utc(max(d.time for d in exits), offset_minutes),
    )


def opened_fact_from_deal(position_id: int | str, entry_deal: Deal, offset_minutes: int) -> OpenedFact:
    """The opened side of a position that was never seen live, from its entry deal alone. Stop and target are 0.0 —
    MT5's own « no stop » convention, not a guess; any rendered capture makes it obvious. Unlike a live detection the
    open time here IS the real fill time."""
    return OpenedFact(
        position_id=str(position_id),
        symbol=entry_deal.symbol,
        side=side_of_deal(entry_deal),
        volume=entry_deal.volume,
        entry_price=entry_deal.price,
        stop_loss=0.0,
        take_profit=0.0,
        opened_at=server_time_to_utc(entry_deal.time, offset_minutes),
        reconstructed=True,
    )


def missed_round_trip_ids(
    recent_deals: Iterable[Deal], known_before_this_poll: set[str], current_ids: set[str]
) -> set[str]:
    """Positions with a recent exit deal that were never seen live and are not open now (so genuinely fully closed — not
    a partial close on a still-open position)."""
    recently_exited = {str(d.position_id) for d in recent_deals if d.entry == DEAL_ENTRY_OUT}
    return recently_exited - known_before_this_poll - current_ids


def scan_window(
    last_scan: datetime | None, now: datetime, first_lookback: timedelta = timedelta(seconds=10)
) -> tuple[datetime, datetime] | None:
    """The deal-history window to scan since the last poll; ``None`` when empty. The very first poll looks back only a
    moment — it must not scan the account's whole history."""
    start = last_scan if last_scan is not None else now - first_lookback
    return (start, now) if start < now else None
