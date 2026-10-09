"""``weekly-review`` — a Markdown review of a week: statistics, compliance rate, most frequent violations, worst trades (port of
``tools/weekly-review``). On demand — nothing schedules it. Facts, not a verdict: the KPI is compliance, not P&L (charter, principle 2).

The statistics are a pure computation over what the journal already judged (the R multiple and the rules each trade broke are the
server's, once); the rendering is a separate pure function, so styling the document can never touch a number.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from trading_os.domain.journal.models import ComplianceSummary, JournalTradeView
from trading_os.shared.numbers import js_round, to_fixed

LABELS = {
    "LOCKOUT_ACTIVE": "Trade during an active lockout",
    "SESSION_WINDOW": "Trade outside the allowed session",
    "SIZE_POLICY": "Size exceeded the risk policy",
}


@dataclass(frozen=True)
class SymbolBreakdown:
    symbol: str
    count: int
    net_realized_pnl: float


@dataclass(frozen=True)
class ViolationTally:
    type: str
    count: int


@dataclass(frozen=True)
class WorstTrade:
    broker_position_id: str
    symbol: str
    side: str
    realized_pnl: float
    closed_at: datetime


@dataclass(frozen=True)
class WeeklyStats:
    week_start: datetime
    week_end: datetime
    trade_count: int
    net_realized_pnl: float
    by_symbol: list[SymbolBreakdown]
    compliance_rate: float
    top_violation_types: list[ViolationTally]
    worst_trades: list[WorstTrade]


def compute_weekly_stats(
    week_start: datetime, week_end: datetime, trades: Sequence[JournalTradeView], compliance: ComplianceSummary
) -> WeeklyStats:
    """``trades`` and ``compliance`` come from the journal for the same window. Added in order, like the original: no ``sum()``."""
    net = 0.0
    for trade in trades:
        net += trade.realized_pnl

    totals: dict[str, tuple[int, float]] = {}
    for trade in trades:
        count, pnl = totals.get(trade.symbol, (0, 0.0))
        totals[trade.symbol] = (count + 1, pnl + trade.realized_pnl)
    by_symbol = sorted(
        (SymbolBreakdown(symbol, count, pnl) for symbol, (count, pnl) in totals.items()), key=lambda s: -s.count
    )

    tallies = sorted(
        (ViolationTally(kind.value, count) for kind, count in compliance.by_type.items() if count > 0),
        key=lambda t: -t.count,
    )[:3]
    worst = sorted(trades, key=lambda t: t.realized_pnl)[:3]
    return WeeklyStats(
        week_start=week_start, week_end=week_end, trade_count=len(trades), net_realized_pnl=net, by_symbol=by_symbol,
        compliance_rate=compliance.rate, top_violation_types=tallies,
        worst_trades=[
            WorstTrade(t.broker_position_id, t.symbol, t.side.value, t.realized_pnl, t.closed_at)
            for t in worst
        ],
    )  # fmt: skip


def money(value: float) -> str:
    return f"{'+' if value >= 0 else '-'}${to_fixed(abs(value), 2)}"


def render_weekly_review(stats: WeeklyStats, cockpit_url: str = "http://localhost:3000") -> str:
    lines: list[str] = []
    label = f"{stats.week_start:%Y-%m-%d} to {stats.week_end:%Y-%m-%d}"
    lines += [
        f"# Weekly review — {label}",
        "",
        "Facts about the week, not a verdict on the strategy — the KPI is compliance, not P&L (charter.md, principe 2). "
        "Generated automatically, zero manual entry.",
        "",
        "## Statistics",
        "",
        f"- Trades closed: **{stats.trade_count}**",
        f"- Net realized P&L: **{money(stats.net_realized_pnl)}**",
    ]
    if stats.by_symbol:
        lines.append("- By symbol:")
        lines += [f"  - {s.symbol}: {s.count} trade(s), {money(s.net_realized_pnl)}" for s in stats.by_symbol]
    lines += ["", "## Compliance", "", f"Weekly compliance rate: **{int(js_round(stats.compliance_rate * 100))}%**", ""]
    if not stats.top_violation_types:
        lines.append("No violations detected this week.")
    else:
        lines += ["Most frequent violations:", ""]
        lines += [f"- {LABELS.get(v.type, v.type)}: {v.count} trade(s)" for v in stats.top_violation_types]
    lines += ["", "## Worst trades", ""]
    if not stats.worst_trades:
        lines.append("No closed trades this week.")
    else:
        for t in stats.worst_trades:
            dossier = (
                f" — [dossier]({cockpit_url}/journal/{t.broker_position_id})"  # the file of the trade: its numbers
            )
            lines.append(f"- {t.closed_at:%Y-%m-%d} · {t.symbol} {t.side.upper()} · {money(t.realized_pnl)}{dossier}")
    lines.append("")
    return "\n".join(lines)
