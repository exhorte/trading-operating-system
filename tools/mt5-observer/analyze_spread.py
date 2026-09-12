"""
Reads the JSONL produced by log_spread.py and reports, per symbol and per
15-minute New York time bucket, the median/p90/p99/max spread in pips.

Throwaway analysis for Phase 0 of the Vague EA plan — same lifecycle as
log_spread.py. Only stdlib (zoneinfo needs the OS tzdata; Windows ships it
via the tzdata package if zoneinfo can't find it — see the except below).

Usage:
    python analyze_spread.py spread_log.jsonl
    python analyze_spread.py spread_log.jsonl --start 07:00 --end 10:30
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, time as dtime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

NY_TZ_NAME = "America/New_York"


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def bucket_key(ts_iso: str, ny_tz) -> tuple[str, dtime]:
    ts = datetime.fromisoformat(ts_iso)
    ny = ts.astimezone(ny_tz)
    minute_bucket = (ny.minute // 15) * 15
    return ny.strftime("%H:%M")[:2] + f":{minute_bucket:02d}", ny.time()


def in_window(ny_time: dtime, start: dtime | None, end: dtime | None) -> bool:
    if start is None or end is None:
        return True
    return start <= ny_time <= end


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    if not values:
        return float("nan")
    k = (len(values) - 1) * p
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def parse_hhmm(s: str | None) -> dtime | None:
    if s is None:
        return None
    h, m = s.split(":")
    return dtime(int(h), int(m))


def main() -> None:
    parser = argparse.ArgumentParser(description="Spread stats by symbol and NY 15-min bucket")
    parser.add_argument("path", type=Path)
    parser.add_argument("--start", help="NY time HH:MM, inclusive (e.g. 02:30 for London open)")
    parser.add_argument("--end", help="NY time HH:MM, inclusive (e.g. 10:30 for NY morning)")
    args = parser.parse_args()

    if ZoneInfo is None:
        raise SystemExit("zoneinfo unavailable — install tzdata: pip install tzdata")
    ny_tz = ZoneInfo(NY_TZ_NAME)

    rows = load_rows(args.path)
    if not rows:
        raise SystemExit(f"[analyze_spread] no rows in {args.path}")

    start = parse_hhmm(args.start)
    end = parse_hhmm(args.end)

    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        pips = row.get("spread_pips")
        if pips is None:
            continue
        label, ny_time = bucket_key(row["ts"], ny_tz)
        if not in_window(ny_time, start, end):
            continue
        buckets[(row["symbol"], label)].append(pips)

    if not buckets:
        raise SystemExit("[analyze_spread] no samples matched the requested window")

    print(f"{'symbol':<12} {'NY bucket':<10} {'n':>6} {'median':>8} {'p90':>8} {'p99':>8} {'max':>8}")
    for (symbol, label) in sorted(buckets):
        values = buckets[(symbol, label)]
        print(
            f"{symbol:<12} {label:<10} {len(values):>6} "
            f"{statistics.median(values):>8.2f} "
            f"{percentile(values, 0.90):>8.2f} "
            f"{percentile(values, 0.99):>8.2f} "
            f"{max(values):>8.2f}"
        )


if __name__ == "__main__":
    main()
