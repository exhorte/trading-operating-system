"""
Spread measured from the broker's own tick history — the replacement for
running log_spread.py live for days. Same lifecycle as log_spread.py and
analyze_spread.py: a throwaway measurement for S01's cost gate, not part of
the domain, not a producer for the cockpit.

Read-only, exactly like mt5_observer.py:
  - no order call of any kind (grep this file: none exist);
  - no TimescaleDB write, no SignalR frame;
  - prints the account's trade mode and server only — never the login or
    the holder's name (.claude/CLAUDE.md).

Each trading day is reduced to one sample per minute:
  - close = spread of the minute's last tick (what a decision taken at the
            M1 close sees — S01 decides on M1 closes);
  - spike = widest spread inside the minute (what a fill can meet).
Windows are New York time (DST-aware). The server clock is assumed to be
UTC + --server-offset (Exness: 0, checked on 2026-09-26 — FX's last tick of
the week lands at 20:59 = 17:00 NY); the script prints the last tick so a
wrong offset shows.

Pass broker names (EURUSDm, XAUUSDm): a canonical name can be ambiguous —
on Exness, XAUUSD matches both XAUUSDm and XAUUSD247m (the 24/7 contract,
2.90 $ spread at weekends), and log_spread.py's resolver takes the first
one (context/domain/symbols-broker.md). Weekend days are skipped.

Usage (terminal open and logged into the account to measure):
    python spread_history.py --symbols EURUSDm XAUUSDm --start 2026-08-31 --end 2026-09-26
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import numpy as np

NY_TZ = ZoneInfo("America/New_York")


def exact_broker_symbol(name: str) -> str | None:
    """The symbol as given if the terminal knows it; otherwise None, with the
    candidates listed — never a guess between two contracts."""
    if mt5.symbol_info(name) is not None:
        return name
    candidates = [s.name for s in (mt5.symbols_get(f"{name}*") or ())]
    print(f"[spread_history] WARNING: {name!r} is not a broker symbol; candidates: {candidates or 'none'}")
    return None

WINDOWS_NY_MINUTES = {
    "london_kz 02-05": (2 * 60, 5 * 60),
    "05-07": (5 * 60, 7 * 60),
    "ny_am_kz 07-10": (7 * 60, 10 * 60),
    "10-12 (before lunch)": (10 * 60, 12 * 60),
    "rollover 16:55-18": (16 * 60 + 55, 18 * 60),
}
KILLZONES = ("london_kz 02-05", "ny_am_kz 07-10")


def pct(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q)) if values.size else float("nan")


def minute_samples(ticks, scale: float, server_offset_h: float):
    """(ny_minute_of_day, close_spread, spike_spread) per minute of `ticks`."""
    tmsc = ticks["time_msc"].astype(np.int64)
    spread = (ticks["ask"] - ticks["bid"]) * scale
    ok = (ticks["ask"] > 0) & (ticks["bid"] > 0)
    tmsc, spread = tmsc[ok], spread[ok]
    if tmsc.size == 0:
        return None
    minute = tmsc // 60000
    starts = np.concatenate(([0], np.flatnonzero(np.diff(minute)) + 1))
    ends = np.concatenate((starts[1:], [minute.size])) - 1
    utc_minutes = minute[starts] - int(server_offset_h * 60)
    ny_minutes = np.array([
        (lambda t: t.hour * 60 + t.minute)(datetime.fromtimestamp(int(m) * 60, timezone.utc).astimezone(NY_TZ))
        for m in utc_minutes
    ])
    return ny_minutes, spread[ends], np.maximum.reduceat(spread, starts), int(tmsc[-1])


def report(broker_name: str, start: datetime, end: datetime, server_offset_h: float) -> None:
    info = mt5.symbol_info(broker_name)
    pip = info.point * 10 if info.digits in (3, 5) else info.point
    # Pips for currency pairs; plain price for metals, where "pip" means
    # something different from one broker to the next (S01, Périmètre).
    metal = info.currency_base in ("XAU", "XAG", "XPT", "XPD")
    unit, scale = ("price", 1.0) if metal else ("pips", 1 / pip)
    print(f"\n=== {broker_name} === digits={info.digits} point={info.point} vol_min={info.volume_min} "
          f"vol_step={info.volume_step} stops_level={info.trade_stops_level} freeze={info.trade_freeze_level} "
          f"spread_float={info.spread_float}")

    closes, spikes = defaultdict(list), defaultdict(list)
    per_day = {}
    last_tick_msc = None
    day = start
    while day < end:
        if day.weekday() >= 5:  # FX and classic gold are closed; a 24/7 contract would skew the windows
            day += timedelta(days=1)
            continue
        ticks = mt5.copy_ticks_range(broker_name, day, day + timedelta(days=1), mt5.COPY_TICKS_INFO)
        sampled = minute_samples(ticks, scale, server_offset_h) if ticks is not None and len(ticks) else None
        if sampled is not None:
            ny_minutes, close, spike, last_tick_msc = sampled
            kz_close = []
            for label, (a, b) in WINDOWS_NY_MINUTES.items():
                sel = (ny_minutes >= a) & (ny_minutes < b)
                closes[label].append(close[sel])
                spikes[label].append(spike[sel])
                if label in KILLZONES:
                    kz_close.append(close[sel])
            kz = np.concatenate(kz_close)
            if kz.size:
                per_day[day.strftime("%a %Y-%m-%d")] = (kz.size, float(np.median(kz)), pct(kz, 95), float(kz.max()))
        day += timedelta(days=1)

    if last_tick_msc is None:
        print("  no ticks in range")
        return
    print(f"  last tick (server clock read as UTC): {datetime.fromtimestamp(last_tick_msc / 1000, timezone.utc)}")
    print(f"  {'window (NY)':<22} {'minutes':>7} | close p50 p90 p95 p99 max | spike p95 p99 max  ({unit})")
    for label in WINDOWS_NY_MINUTES:
        c = np.concatenate(closes[label]) if closes[label] else np.array([])
        s = np.concatenate(spikes[label]) if spikes[label] else np.array([])
        if not c.size:
            continue
        print(f"  {label:<22} {c.size:>7} | {pct(c, 50):.2f} {pct(c, 90):.2f} {pct(c, 95):.2f} {pct(c, 99):.2f} "
              f"{c.max():.2f} | {pct(s, 95):.2f} {pct(s, 99):.2f} {s.max():.2f}")
    print("  killzones per day (minutes, close p50, p95, max):")
    for label, (n, med, p95, mx) in per_day.items():
        print(f"    {label}  {n:>4}  {med:.2f}  {p95:.2f}  {mx:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Spread per NY window from MT5 tick history (read-only)")
    parser.add_argument("--symbols", nargs="+", default=["EURUSDm", "XAUUSDm"], help="broker names")
    parser.add_argument("--start", required=True, help="UTC date, YYYY-MM-DD, inclusive")
    parser.add_argument("--end", required=True, help="UTC date, YYYY-MM-DD, exclusive")
    parser.add_argument("--server-offset", type=float, default=0.0, help="server clock minus UTC, hours (Exness: 0)")
    args = parser.parse_args()

    if not mt5.initialize():
        raise SystemExit(f"[spread_history] mt5.initialize() failed: {mt5.last_error()}")
    try:
        acc = mt5.account_info()
        mode = {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(acc.trade_mode, str(acc.trade_mode))
        print(f"[spread_history] READ-ONLY. account trade_mode={mode} server={acc.server} currency={acc.currency}")
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
        for name in args.symbols:
            broker_name = exact_broker_symbol(name)
            if broker_name is None:
                continue
            mt5.symbol_select(broker_name, True)
            report(broker_name, start, end, args.server_offset)
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
