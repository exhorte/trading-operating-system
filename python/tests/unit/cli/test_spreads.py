"""``spread-history``: the spread per New York window, from tick history — the sampling, the percentiles, the units and the windows."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from trading_os.cli.history import parse_utc
from trading_os.cli.spreads import (
    WINDOWS_NY_MINUTES,
    MinuteSample,
    minute_samples,
    percentile,
    render,
    report_symbol,
)
from trading_os.cli.terminal import ReadOnlyTerminal
from trading_os.infrastructure.mt5.fake import FakeMt5
from trading_os.infrastructure.mt5.transport import InProcessTransport


def tick(minute: int, second: int, bid: float, ask: float) -> dict[str, float]:
    return {"time_msc": (minute * 60 + second) * 1000, "bid": bid, "ask": ask}


# ------------------------------------------------------------------------------------------------------ the arithmetic


def test_a_percentile_interpolates_linearly_like_numpy() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0) == 1 and percentile(values, 100) == 4
    assert percentile(values, 50) == pytest.approx(2.5) and percentile(values, 95) == pytest.approx(3.85)
    assert percentile([7.0], 99) == 7.0 and math.isnan(percentile([], 50))
    assert percentile([4.0, 1.0, 3.0, 2.0], 50) == percentile(values, 50)  # order does not matter


def test_a_minute_keeps_the_spread_of_its_last_tick_and_the_widest_one_it_saw() -> None:
    ticks = [
        tick(100, 1, 1.0, 1.0001),  # 1 pip
        tick(100, 30, 1.0, 1.0003),  # 3 pips (the spike)
        tick(100, 59, 1.0, 1.0002),  # 2 pips (the close)
        tick(101, 5, 1.0, 1.0001),
    ]
    samples, last = minute_samples(ticks, scale=1 / 0.0001, server_offset_h=0) or ([], 0)
    assert [(round(s.close, 6), round(s.spike, 6)) for s in samples] == [(2.0, 3.0), (1.0, 1.0)]
    assert last == (101 * 60 + 5) * 1000


def test_ticks_without_a_bid_or_an_ask_are_dropped_and_nothing_left_is_none() -> None:
    assert minute_samples([tick(1, 0, 0.0, 1.0), tick(1, 1, 1.0, 0.0)], 1.0, 0) is None
    assert minute_samples([], 1.0, 0) is None
    samples, _ = minute_samples([tick(1, 0, 0.0, 1.0), tick(1, 5, 1.0, 1.5)], 1.0, 0) or ([], 0)
    assert samples == [MinuteSample(samples[0].ny_minute, 0.5, 0.5)]


def test_the_new_york_minute_follows_the_zone_and_its_dst() -> None:
    winter = int(datetime(2026, 1, 15, 8, 30, tzinfo=UTC).timestamp()) // 60  # 03:30 NY (EST)
    summer = int(datetime(2026, 6, 15, 8, 30, tzinfo=UTC).timestamp()) // 60  # 04:30 NY (EDT)
    got_winter = minute_samples([{"time_msc": winter * 60_000, "bid": 1.0, "ask": 1.1}], 1.0, 0)
    got_summer = minute_samples([{"time_msc": summer * 60_000, "bid": 1.0, "ask": 1.1}], 1.0, 0)
    assert got_winter is not None and got_summer is not None
    assert got_winter[0][0].ny_minute == 3 * 60 + 30 and got_summer[0][0].ny_minute == 4 * 60 + 30


def test_a_server_clock_ahead_of_utc_is_corrected_before_the_zone_is_applied() -> None:
    server_minute = (
        int(datetime(2026, 1, 15, 10, 30, tzinfo=UTC).timestamp()) // 60
    )  # the broker's clock reads 10:30 = 08:30 UTC
    got = minute_samples([{"time_msc": server_minute * 60_000, "bid": 1.0, "ask": 1.1}], 1.0, server_offset_h=2)
    assert got is not None and got[0][0].ny_minute == 3 * 60 + 30  # 08:30 UTC = 03:30 NY in winter


def test_the_windows_are_the_ones_the_cost_gate_was_measured_on() -> None:
    assert WINDOWS_NY_MINUTES["london_kz 02-05"] == (120, 300) and WINDOWS_NY_MINUTES["ny_am_kz 07-10"] == (420, 600)


# ------------------------------------------------------------------------------------------------------ a whole report


class QuotedDay(FakeMt5):
    """A simulated terminal whose tick history is two ticks a minute from 07:00 to 09:59 UTC every day: 0.8 pip then 1.2 pip."""

    def copy_ticks_range(self, *args: Any, **kwargs: Any) -> Any:
        first = int(args[1])
        ticks = []
        for minute in range(7 * 60, 10 * 60):
            base = first + minute * 60
            ticks.append({"time_msc": (base + 1) * 1000, "bid": 1.08, "ask": 1.08 + 0.00008, "flags": 6})
            ticks.append({"time_msc": (base + 40) * 1000, "bid": 1.08, "ask": 1.08 + 0.00012, "flags": 6})
        return ticks


async def test_a_report_reduces_each_window_to_the_close_and_the_spike() -> None:
    terminal = ReadOnlyTerminal(InProcessTransport(QuotedDay.default()))
    async with terminal:
        report = await report_symbol(terminal, "EURUSDm", parse_utc("2026-01-05"), parse_utc("2026-01-07"), 0.0)
    assert report is not None and report.unit == "pips"
    text = "\n".join(render(report))
    assert "=== EURUSDm === digits=5" in text and "last tick (server clock read as UTC)" in text
    london = next(line for line in report.window_lines if line.startswith("  london_kz 02-05"))
    # 07:00-10:00 UTC is 02:00-05:00 NY in winter: 180 minutes a day over two weekdays; the close is the 1.2 pip tick, the spike too
    assert " 360 | 1.20 1.20 1.20 1.20 1.20 | 1.20 1.20 1.20" in london
    assert not any(line.startswith("  ny_am_kz") for line in report.window_lines)  # no tick falls in 07:00-10:00 NY
    assert len(report.day_lines) == 2 and "Mon 2026-01-05" in report.day_lines[0]


async def test_weekend_days_are_skipped_and_a_symbol_the_terminal_does_not_know_has_no_report() -> None:
    terminal = ReadOnlyTerminal(InProcessTransport(QuotedDay.default()))
    async with terminal:
        saturday = await report_symbol(terminal, "EURUSDm", parse_utc("2026-01-10"), parse_utc("2026-01-12"), 0.0)
        assert saturday is not None and saturday.last_tick is None
        assert "no ticks in range" in "\n".join(render(saturday))
        assert await report_symbol(terminal, "NOPE", parse_utc("2026-01-05"), parse_utc("2026-01-06"), 0.0) is None
