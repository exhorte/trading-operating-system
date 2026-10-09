"""The Python analysis engine against golden vectors generated from the TypeScript original (``tests/golden/analysis.json``).

Comparison is exact: both sides do the same IEEE-754 arithmetic in the same order, so any difference is a porting bug (a rounding
mode, a summation order, a tie-break) and not noise. The vectors cover random walks at gold and FX scales, several swing
lookbacks and tolerances, forming last bars, coarse prices with many ties, sessions that wrap midnight, and bucket alignment.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from trading_os.domain.market.analysis import (
    AnalysisConfig,
    aggregate_candles,
    analyze_market_context,
    average_true_range,
)
from trading_os.domain.market.analysis.bias import compute_bias, price_location_of
from trading_os.domain.market.analysis.liquidity import detect_liquidity
from trading_os.domain.market.analysis.pd_arrays import detect_fair_value_gaps, detect_order_blocks
from trading_os.domain.market.analysis.structure import detect_structure_shifts, structural_bias
from trading_os.domain.market.analysis.swings import detect_swings
from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import SessionWindow, session_enabled, session_for_timestamp
from trading_os.domain.primitives import Timeframe, TradingSession

GOLDEN = json.loads((Path(__file__).parents[3] / "golden" / "analysis.json").read_text(encoding="utf-8"))
CASES: list[dict[str, Any]] = GOLDEN["cases"]
MILLIS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.000Z$")


def canon(value: Any) -> Any:
    """JavaScript writes ``…:00.000Z``, pydantic ``…:00Z``: the same instant."""
    if isinstance(value, str):
        match = MILLIS.match(value)
        return f"{match.group(1)}Z" if match else value
    if isinstance(value, list):
        return [canon(v) for v in value]
    if isinstance(value, dict):
        return {k: canon(v) for k, v in value.items()}
    return value


def dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, list):
        return [dump(v) for v in value]
    return value


def own_fvgs(case: dict[str, Any]) -> list[dict[str, Any]]:
    """The gaps found with the case's own minimum size."""
    found: list[dict[str, Any]] = case["fairValueGaps"]["own"]
    return found


def dump_time(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def candles_of(case: dict[str, Any]) -> list[Candle]:
    return [Candle.model_validate(c) for c in case["candles"]]


def ids(cases: list[dict[str, Any]]) -> list[str]:
    return [c["name"] for c in cases]


case = pytest.mark.parametrize("case", CASES, ids=ids(CASES))


def test_the_vectors_are_not_trivially_empty() -> None:
    """A golden file that quietly holds nothing would pass every comparison below."""
    populated = [c for c in CASES if c["candles"]]
    assert len(populated) >= 12
    assert sum(len(c["swings"]["2"]) for c in populated) > 150
    assert sum(len(own_fvgs(c)) for c in populated) > 1000
    assert sum(1 for c in populated for g in own_fvgs(c) if 0 < g["filledPercent"] < 100) >= 5
    assert sum(1 for c in populated for g in own_fvgs(c) if g["mitigatedAt"]) > 100
    assert {g["direction"] for c in populated for g in own_fvgs(c)} == {"bullish", "bearish"}
    assert sum(len(s["shifts"]) for c in populated for s in c["structure"].values()) > 100
    assert sum(len(v) for c in populated for v in c["liquidity"].values()) > 30
    kinds = {s["kind"] for c in populated for st in c["structure"].values() for s in st["shifts"]}
    assert kinds == {"break_of_structure", "change_of_character"}
    assert any(c["context"]["lastStructureShift"] for c in populated)
    assert any(c["context"]["activeFairValueGaps"] for c in populated)
    assert any(c["context"]["activeOrderBlocks"] for c in populated)
    assert {c["context"]["bias"] for c in populated} >= {"bullish", "bearish"}
    assert {c["priceLocation"] for c in populated} >= {"premium", "discount", "equilibrium"}
    levels = {lv["kind"] for c in populated for v in c["liquidity"].values() for lv in v}
    assert levels >= {"equal_highs", "equal_lows", "previous_day_high", "previous_day_low"}
    assert any(lv["sweptAt"] for c in populated for v in c["liquidity"].values() for lv in v)
    assert any(lv["sweptAt"] is None for c in populated for v in c["liquidity"].values() for lv in v)


@case
def test_swings(case: dict[str, Any]) -> None:
    candles = candles_of(case)
    for lookback, expected in case["swings"].items():
        assert dump(detect_swings(candles, int(lookback))) == canon(expected), lookback


@case
def test_structure_shifts_bias_and_order_blocks(case: dict[str, Any]) -> None:
    candles = candles_of(case)
    for lookback, expected in case["structure"].items():
        swings = detect_swings(candles, int(lookback))
        shifts = detect_structure_shifts(candles, swings, int(lookback))
        assert dump(shifts) == canon(expected["shifts"]), lookback
        assert structural_bias(shifts).value == expected["bias"], lookback
        assert dump(detect_order_blocks(candles, shifts)) == canon(expected["orderBlocks"]), lookback


@case
def test_liquidity(case: dict[str, Any]) -> None:
    candles = candles_of(case)
    swings = detect_swings(candles, AnalysisConfig.model_validate(case["config"]).swing_lookback)
    for tolerance, expected in case["liquidity"].items():
        assert dump(detect_liquidity(candles, swings, float(tolerance))) == canon(expected), tolerance


@case
def test_fair_value_gaps(case: dict[str, Any]) -> None:
    candles = candles_of(case)
    config = AnalysisConfig.model_validate(case["config"])
    assert dump(detect_fair_value_gaps(candles, config.min_fvg_size)) == canon(case["fairValueGaps"]["own"])
    for minimum, digest in case["fairValueGaps"]["variants"].items():
        gaps = detect_fair_value_gaps(candles, float(minimum))
        assert [g.fvg_id for g in gaps] == digest["ids"], minimum
        assert [g.direction.value for g in gaps] == digest["directions"], minimum
        assert [g.filled_percent for g in gaps] == digest["filledPercent"], minimum
        assert [dump_time(g.mitigated_at) for g in gaps] == canon(digest["mitigatedAt"]), minimum


@case
def test_atr(case: dict[str, Any]) -> None:
    candles = candles_of(case)
    for period, expected in case["atr"].items():
        assert average_true_range(candles, int(period)) == expected, period  # bit for bit


@case
def test_price_location_and_bias(case: dict[str, Any]) -> None:
    candles = candles_of(case)
    config = AnalysisConfig.model_validate(case["config"])
    swings = detect_swings(candles, config.swing_lookback)
    last_close = candles[-1].close if candles else 0.0
    assert price_location_of(last_close, swings) == case["priceLocation"]
    shifts = detect_structure_shifts(candles, swings, config.swing_lookback)
    assert compute_bias(structural_bias(shifts)).value == case["bias"]


@case
def test_the_whole_market_context(case: dict[str, Any]) -> None:
    candles = candles_of(case)
    config = AnalysisConfig.model_validate(case["config"])
    state = analyze_market_context(case["symbol"], Timeframe(case["timeframe"]), candles, config)
    assert dump(state) == canon(case["context"])


# ------------------------------------------------------------------------------------------------------ sessions


def windows_of(raw: list[dict[str, Any]]) -> list[SessionWindow]:
    return [SessionWindow.model_validate(w) for w in raw]


@pytest.mark.parametrize("name", ["default", "custom", "none"])
def test_sessions_bucket_every_five_minutes_of_two_days_like_the_original(name: str) -> None:
    sessions = GOLDEN["sessions"]
    windows = windows_of(sessions["windows"][name])
    stamps = [datetime.fromisoformat(s.replace("Z", "+00:00")) for s in sessions["stamps"]]
    assert [session_for_timestamp(ts, windows).value for ts in stamps] == sessions["sessions"][name]
    names = ["asia", "london", "new_york_am", "new_york_pm", "off_session"]
    assert [session_enabled(TradingSession(n), windows) for n in names] == sessions["enabled"][name]


# ------------------------------------------------------------------------------------------------------ aggregation


def test_aggregation_aligns_buckets_to_the_epoch_like_the_original() -> None:
    aggregate = GOLDEN["aggregate"]
    m1 = [Candle.model_validate(c) for c in aggregate["m1"]]
    assert aggregate["m1"][0]["openTime"] == "2026-01-05T00:07:00.000Z"  # deliberately not on an hour boundary
    for target, expected in aggregate["fromM1"].items():
        assert dump(aggregate_candles(m1, Timeframe.M1, Timeframe(target))) == canon(expected), target
        assert expected, target
    m5 = aggregate_candles(m1, Timeframe.M1, Timeframe.M5)
    for target, expected in aggregate["fromM5"].items():
        assert dump(aggregate_candles(m5, Timeframe.M5, Timeframe(target))) == canon(expected), target
    assert aggregate_candles([], Timeframe.M1, Timeframe.H1) == aggregate["empty"] == []
