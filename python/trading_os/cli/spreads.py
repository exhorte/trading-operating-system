"""``spread-history`` — the spread measured from the broker's own tick history, per New York window (port of
``tools/mt5-observer/spread_history.py``). A throwaway measurement for S01's cost gate, not part of the domain.

Read-only like everything here: no order call exists in the worker, nothing is written to the database. It prints the account's trade
mode and server — never the login or the holder's name.

Each trading day is reduced to one sample per minute:

* ``close`` — the spread of the minute's last tick (what a decision taken at the M1 close sees: S01 decides on M1 closes);
* ``spike`` — the widest spread inside the minute (what a fill can meet).

Windows are New York time (DST-aware). The server clock is assumed to be UTC + ``--server-offset`` (Exness: 0, checked on 2026-09-26: FX's
last tick of the week lands at 20:59 = 17:00 NY); the last tick is printed so a wrong offset shows. Pass **broker names** (EURUSDm,
XAUUSDm): a canonical name can be ambiguous (on Exness XAUUSD matches both XAUUSDm and XAUUSD247m, the 24/7 contract). Weekend days are skipped.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trading_os.cli.terminal import ReadOnlyTerminal
from trading_os.domain.market.sessions import NY_TIME_ZONE

WINDOWS_NY_MINUTES: dict[str, tuple[int, int]] = {
    "london_kz 02-05": (2 * 60, 5 * 60),
    "05-07": (5 * 60, 7 * 60),
    "ny_am_kz 07-10": (7 * 60, 10 * 60),
    "10-12 (before lunch)": (10 * 60, 12 * 60),
    "rollover 16:55-18": (16 * 60 + 55, 18 * 60),
}
KILLZONES = ("london_kz 02-05", "ny_am_kz 07-10")
METALS = frozenset({"XAU", "XAG", "XPT", "XPD"})


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q``-th percentile with linear interpolation (numpy's default); NaN for no values."""
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def median(values: Sequence[float]) -> float:
    return percentile(values, 50)


@dataclass(frozen=True)
class MinuteSample:
    ny_minute: int  # minute of the New York day
    close: float  # spread of the minute's last tick
    spike: float  # widest spread inside the minute


def minute_samples(
    ticks: Sequence[Mapping[str, float]], scale: float, server_offset_h: float
) -> tuple[list[MinuteSample], int] | None:
    """One sample per minute of ``ticks`` (bid/ask changes, oldest first) and the last tick's millisecond time. Ticks with no
    bid or no ask are dropped; ``None`` when nothing is left."""
    usable = [t for t in ticks if t["ask"] > 0 and t["bid"] > 0]
    if not usable:
        return None
    samples: list[MinuteSample] = []
    current: int | None = None
    close = spike = 0.0
    for tick in usable:
        minute = int(tick["time_msc"]) // 60_000
        spread = (tick["ask"] - tick["bid"]) * scale
        if minute != current:
            if current is not None:
                samples.append(MinuteSample(_ny_minute(current, server_offset_h), close, spike))
            current, spike = minute, spread
        else:
            spike = max(spike, spread)
        close = spread
    assert current is not None
    samples.append(MinuteSample(_ny_minute(current, server_offset_h), close, spike))
    return samples, int(usable[-1]["time_msc"])


def _ny_minute(server_minute: int, server_offset_h: float) -> int:
    utc_minute = server_minute - int(server_offset_h * 60)
    local = datetime.fromtimestamp(utc_minute * 60, UTC).astimezone(NY_TIME_ZONE)
    return local.hour * 60 + local.minute


@dataclass
class SymbolReport:
    header: str
    last_tick: datetime | None
    unit: str
    window_lines: list[str]
    day_lines: list[str]


def format_window(label: str, closes: Sequence[float], spikes: Sequence[float]) -> str:
    return (
        f"  {label:<22} {len(closes):>7} | {percentile(closes, 50):.2f} {percentile(closes, 90):.2f} "
        f"{percentile(closes, 95):.2f} {percentile(closes, 99):.2f} {max(closes):.2f} | "
        f"{percentile(spikes, 95):.2f} {percentile(spikes, 99):.2f} {max(spikes):.2f}"
    )


async def report_symbol(
    terminal: ReadOnlyTerminal, name: str, start: datetime, end: datetime, server_offset_h: float
) -> SymbolReport | None:
    info = await terminal.symbol_info(name)
    if info is None:
        return None
    digits, point = int(info.get("digits", 5)), float(info.get("point", 0.00001))
    pip = point * 10 if digits in (3, 5) else point
    # Pips for currency pairs; plain price for metals, where « pip » means something different from one broker to the next.
    metal = str(info.get("currency_base", "")) in METALS
    unit, scale = ("price", 1.0) if metal else ("pips", 1 / pip)
    header = (
        f"=== {name} === digits={digits} point={point} vol_min={info.get('volume_min')} vol_step={info.get('volume_step')} "
        f"stops_level={info.get('trade_stops_level')} freeze={info.get('trade_freeze_level')} "
        f"spread_float={info.get('spread_float')}"
    )

    closes: dict[str, list[float]] = defaultdict(list)
    spikes: dict[str, list[float]] = defaultdict(list)
    per_day: dict[str, tuple[int, float, float, float]] = {}
    last_tick_msc: int | None = None
    day = start
    while day < end:
        if day.weekday() >= 5:  # FX and classic gold are closed; a 24/7 contract would skew the windows
            day += timedelta(days=1)
            continue
        first = int(day.timestamp()) + int(server_offset_h * 3600)
        ticks = await terminal.ticks_between(name, first, first + 86_400)
        sampled = minute_samples(ticks, scale, server_offset_h) if ticks else None
        if sampled is not None:
            samples, last_tick_msc = sampled
            killzone_closes: list[float] = []
            for label, (a, b) in WINDOWS_NY_MINUTES.items():
                inside = [s for s in samples if a <= s.ny_minute < b]
                closes[label] += [s.close for s in inside]
                spikes[label] += [s.spike for s in inside]
                if label in KILLZONES:
                    killzone_closes += [s.close for s in inside]
            if killzone_closes:
                per_day[day.strftime("%a %Y-%m-%d")] = (
                    len(killzone_closes), median(killzone_closes), percentile(killzone_closes, 95), max(killzone_closes),
                )  # fmt: skip
        day += timedelta(days=1)

    if last_tick_msc is None:
        return SymbolReport(header, None, unit, [], [])
    windows = [format_window(label, closes[label], spikes[label]) for label in WINDOWS_NY_MINUTES if closes[label]]
    days = [f"    {label}  {n:>4}  {med:.2f}  {p95:.2f}  {mx:.2f}" for label, (n, med, p95, mx) in per_day.items()]
    return SymbolReport(header, datetime.fromtimestamp(last_tick_msc / 1000, UTC), unit, windows, days)


def render(report: SymbolReport) -> list[str]:
    lines = ["", report.header]
    if report.last_tick is None:
        return [*lines, "  no ticks in range"]
    lines.append(f"  last tick (server clock read as UTC): {report.last_tick}")
    lines.append(
        f"  {'window (NY)':<22} {'minutes':>7} | close p50 p90 p95 p99 max | spike p95 p99 max  ({report.unit})"
    )
    lines += report.window_lines
    lines.append("  killzones per day (minutes, close p50, p95, max):")
    return lines + report.day_lines
