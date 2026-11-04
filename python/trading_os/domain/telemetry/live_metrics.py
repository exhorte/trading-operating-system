"""Live measurements (ADR 0035, L1): the quotes, the agent link and the commands as they really were, in numbers.

Pure functions and models: nothing here reads a clock, a database or the network. Nothing is invented either — a figure that
cannot be taken is ``None`` (or an empty distribution) and is named in ``LiveMetrics.not_measured``, never replaced by a
default. Percentiles are *nearest rank*: every figure shown is a value that really occurred, none is interpolated.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime

from pydantic import Field

from trading_os.domain.execution.commands import CommandState, ExecutionCommand
from trading_os.domain.primitives import DomainModel

# A day of stored ticks at one a second is 86 400 rows: the database summarises them, Python never holds them.
MAX_WINDOW_MINUTES = 1440

# What the measures can and cannot say. They travel with every report so that a number is never read without its limit.
CAVEATS: tuple[str, ...] = (
    "Quote times come from the broker at one-second resolution and the core reads each symbol once a second: "
    "the receipt lag is known to about two seconds, and the stored ticks are the ones seen at that rate, not every tick.",
    "Percentiles are nearest rank (a value that occurred); the spread is in price units, the receipt lag in seconds.",
    "Command durations come from the core's own clock (sent, acknowledged, completed) and leave out SIMULATED commands: "
    "no broker order exists for those.",
)


class Distribution(DomainModel):
    """``n`` observations summarised by values that really occurred. Empty (``n = 0``) means *not measured*."""

    n: int
    min: float | None = None
    median: float | None = None
    p95: float | None = None
    max: float | None = None


def _nearest_rank(ordered: Sequence[float], q: float) -> float:
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def distribution(values: Iterable[float], *, digits: int = 10) -> Distribution:
    ordered = sorted(round(v, digits) for v in values)
    if not ordered:
        return Distribution(n=0)
    return Distribution(
        n=len(ordered),
        min=ordered[0],
        median=_nearest_rank(ordered, 0.5),
        p95=_nearest_rank(ordered, 0.95),
        max=ordered[-1],
    )


def ticks_per_minute(ticks: int, span_s: float | None) -> float | None:
    """Observed rate over the stored span: ``n - 1`` intervals in ``span``. ``None`` under two ticks."""
    if ticks < 2 or span_s is None or span_s <= 0:
        return None
    return round((ticks - 1) / span_s * 60, 2)


class QuoteMetrics(DomainModel):
    symbol: str
    ticks: int  # stored ticks in the window
    span_s: float | None = None  # first to last stored tick
    ticks_per_minute: float | None = None
    spread: Distribution  # price units, from the stored ticks
    last_tick_age_s: float | None = None  # the newest quote the core holds, against now
    market_open: bool | None = None  # so that a stale quote on a closed market is not read as a dead feed
    receipt_lag_s: Distribution  # tick time to the moment the core saw it, since the core started


class AgentLinkMetrics(DomainModel):
    connected: bool
    last_heartbeat_age_s: float | None = None


class CommandMetrics(DomainModel):
    total: int
    by_state: dict[str, int] = Field(default_factory=dict)
    reject_codes: dict[str, int] = Field(default_factory=dict)
    broker_retcodes: dict[str, int] = Field(default_factory=dict)
    simulated: int = 0  # validated end to end, no broker order exists: left out of every duration below
    ack_s: Distribution  # sent to acknowledged: the round trip core, agent, core
    fill_s: Distribution  # acknowledged to completed: the broker's side
    total_s: Distribution  # created to completed
    inconsistent: int = 0  # commands whose timestamps ran backwards: left out, counted, never corrected


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def command_metrics(commands: Sequence[ExecutionCommand]) -> CommandMetrics:
    simulated = [c for c in commands if c.state is CommandState.SIMULATED]
    real = [c for c in commands if c.state is not CommandState.SIMULATED]
    ack: list[float] = []
    fill: list[float] = []
    total: list[float] = []
    inconsistent = 0
    for command in real:
        measured = (
            (ack, _seconds(command.sent_at, command.acknowledged_at)),
            (fill, _seconds(command.acknowledged_at, command.completed_at)),
            (total, _seconds(command.created_at, command.completed_at)),
        )
        backwards = False
        for bucket, seconds in measured:
            if seconds is None:
                continue
            if seconds < 0:
                backwards = True
                continue
            bucket.append(seconds)
        inconsistent += backwards
    return CommandMetrics(
        total=len(commands),
        by_state=dict(sorted(Counter(c.state.value for c in commands).items())),
        reject_codes=dict(sorted(Counter(c.reject_code for c in real if c.reject_code).items())),
        broker_retcodes=dict(sorted(Counter(c.broker_retcode for c in real if c.broker_retcode).items())),
        simulated=len(simulated),
        ack_s=distribution(ack),
        fill_s=distribution(fill),
        total_s=distribution(total),
        inconsistent=inconsistent,
    )


def not_measured(
    quotes: Sequence[QuoteMetrics],
    agent: AgentLinkMetrics | None,
    commands: CommandMetrics,
    *,
    terminal_connected: bool = True,
) -> list[str]:
    """What this window could not tell, said in words — the report never fills a hole with a default.
    ``agent`` is ``None`` when the report does not query a running core (the CLI): the link is then not observed.
    ``terminal_connected`` is false when the core holds no session for the account: it then reads no quote at all."""
    gaps: list[str] = []
    if not terminal_connected:
        gaps.append(
            "the account is not connected to the terminal: the core reads no quote, so there is no lag to measure"
        )
    for quote in quotes:
        if quote.ticks == 0:
            gaps.append(f"{quote.symbol}: no tick stored in the window (spread and rate unknown)")
        if quote.receipt_lag_s.n == 0:
            gaps.append(f"{quote.symbol}: no quote seen by a running core in the window (receipt lag unknown)")
    if agent is None:
        gaps.append("the agent link is not observed by this report: it reads the database, not a running core")
    elif not agent.connected:
        gaps.append("no execution agent is connected: nothing about the link, the acknowledgements or the fills")
    gaps.append(
        "idle latency between the core and the agent: the agent reports a constant latencyMs of 0 and does not echo "
        "the core's ping, so only the command round trip (sent to acknowledged) is a measure"
    )
    if commands.total == 0:
        gaps.append("no command in the window: the broker's responses, rejections and fills are not measured")
    elif commands.total == commands.simulated:
        gaps.append("every command in the window was SIMULATED: no broker response exists to measure")
    gaps.append("slippage, real commission and swap: known only from filled deals, not measured here")
    return gaps


class LiveMetrics(DomainModel):
    observed_at: datetime
    account_id: str
    window_minutes: int
    quotes: list[QuoteMetrics]
    agent: AgentLinkMetrics
    commands: CommandMetrics
    caveats: list[str]
    not_measured: list[str]
