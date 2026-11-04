"""``live-report``: the live measures of a window as a Markdown page, from the stored ticks and commands (ADR 0035, L1).

It reads the database only — no running core, no terminal, nothing written but the report — so it can be run before and
after a change, on any past window, and the two pages compared line by line.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from trading_os.domain.telemetry.live_metrics import (
    CAVEATS,
    CommandMetrics,
    Distribution,
    QuoteMetrics,
    not_measured,
)


def _figure(value: float | None, unit: str = "") -> str:
    """Fixed notation without trailing zeros: a spread of 0.00008 is read as such, not as 8e-05."""
    if value is None:
        return "—"
    return (f"{value:.8f}".rstrip("0").rstrip(".") or "0") + unit


def _row(label: str, d: Distribution, unit: str = "") -> str:
    if d.n == 0:
        return f"| {label} | 0 | — | — | — | — |"
    return (
        f"| {label} | {d.n} | {_figure(d.min, unit)} | {_figure(d.median, unit)} | {_figure(d.p95, unit)} "
        f"| {_figure(d.max, unit)} |"
    )


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name} × {n}" for name, n in counts.items()) if counts else "none"


def render_live_report(
    *, account_id: str, start: datetime, end: datetime, quotes: Sequence[QuoteMetrics], commands: CommandMetrics
) -> str:
    lines = [
        f"# Live measures — {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} UTC",
        "",
        f"Account `{account_id}`. Read from the database; nothing was sent to a terminal or an agent.",
        "",
        "## Quotes (stored ticks)",
        "",
        "| Symbol | Ticks | Span (s) | Ticks/min | Spread min | Median | p95 | Max |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for q in quotes:
        s = q.spread
        lines.append(
            f"| {q.symbol} | {q.ticks} | {_figure(q.span_s)} | {_figure(q.ticks_per_minute)} | {_figure(s.min)} "
            f"| {_figure(s.median)} | {_figure(s.p95)} | {_figure(s.max)} |"
        )
    lines += [
        "",
        "## Commands",
        "",
        f"{commands.total} command(s), of which {commands.simulated} simulated (no broker order exists for those).",
        "",
        f"- States: {_counts(commands.by_state)}",
        f"- Refusals before the broker: {_counts(commands.reject_codes)}",
        f"- Broker return codes: {_counts(commands.broker_retcodes)}",
        f"- Commands whose timestamps ran backwards (left out): {commands.inconsistent}",
        "",
        "| Duration (s) | n | min | median | p95 | max |",
        "|---|---|---|---|---|---|",
        _row("Sent → acknowledged (core, agent, core)", commands.ack_s),
        _row("Acknowledged → completed (broker side)", commands.fill_s),
        _row("Created → completed", commands.total_s),
        "",
        "## Not measured",
        "",
    ]
    lines += [f"- {gap}" for gap in not_measured(quotes, None, commands)]
    lines += ["", "## Reading these figures", ""]
    lines += [f"- {caveat}" for caveat in CAVEATS]
    return "\n".join(lines) + "\n"
