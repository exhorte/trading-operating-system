"""The analysis engine's behaviour, stated as readable cases (the TypeScript tests of ``lib/analysis``, carried over). The golden vectors
prove the port computes what the original did; these say what that is."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.support.candles import candle_at, series
from trading_os.domain.market.analysis import DEFAULT_ANALYSIS_CONFIG, aggregate_candles, analyze_market_context
from trading_os.domain.market.analysis.atr import average_true_range
from trading_os.domain.market.analysis.bias import compute_bias, price_location_of
from trading_os.domain.market.analysis.liquidity import detect_liquidity
from trading_os.domain.market.analysis.models import (
    AnalysisFeatures,
    FairValueGap,
    LiquidityKind,
    StructureShift,
    StructureShiftKind,
    Swing,
)
from trading_os.domain.market.analysis.pd_arrays import detect_fair_value_gaps, detect_order_blocks
from trading_os.domain.market.analysis.scoring import score_context
from trading_os.domain.market.analysis.structure import detect_structure_shifts, structural_bias
from trading_os.domain.market.analysis.swings import detect_swings
from trading_os.domain.market.sessions import DEFAULT_SESSION_WINDOWS, session_enabled, session_for_timestamp
from trading_os.domain.primitives import Bias, Timeframe, TradingSession

T = datetime(2026, 1, 5, tzinfo=UTC)


# ------------------------------------------------------------------------------------------------------ swings


def test_a_strict_swing_high_and_low_with_lookback_one() -> None:
    candles = series([(10, 8), (11, 9), (9, 5), (12, 7), (10, 8)])
    swings = detect_swings(candles, 1)
    assert any(s.kind == "high" and s.index == 1 and s.price == 11 for s in swings)
    assert any(s.kind == "low" and s.index == 2 and s.price == 5 for s in swings)


def test_no_pivot_is_reported_inside_the_trailing_lookback_window() -> None:
    assert detect_swings(series([(10, 8), (11, 9), (12, 7), (11, 9)]), 2) == []  # (no look-ahead)


def test_a_flat_top_is_not_a_swing_high() -> None:
    candles = series([(10, 8), (12, 9), (12, 9), (11, 8)])
    assert [s for s in detect_swings(candles, 1) if s.kind == "high"] == []


# ------------------------------------------------------------------------------------------------------ structure


STRUCTURE = series(
    [
        {"high": 10, "low": 8, "close": 9},
        {"high": 12, "low": 9, "close": 11},  # swing high 12
        {"high": 11, "low": 9, "close": 10},  # confirms it
        {"high": 13, "low": 10, "close": 12.5},  # close > 12 -> BOS bullish
        {"high": 13, "low": 11, "close": 12},
        {"high": 12, "low": 9, "close": 10},  # swing low 9
        {"high": 11, "low": 10, "close": 10.5},  # confirms it
        {"high": 10, "low": 7, "close": 8},  # close < 9 while bullish -> CHOCH bearish
    ]
)


def test_a_bullish_break_of_structure_then_a_bearish_change_of_character() -> None:
    shifts = detect_structure_shifts(STRUCTURE, detect_swings(STRUCTURE, 1), 1)
    assert [(s.kind, s.direction, s.broken_level) for s in shifts] == [
        (StructureShiftKind.BREAK_OF_STRUCTURE, Bias.BULLISH, 12),
        (StructureShiftKind.CHANGE_OF_CHARACTER, Bias.BEARISH, 9),
    ]
    assert structural_bias(shifts) is Bias.BEARISH


def test_without_a_break_the_bias_is_neutral() -> None:
    flat = series([(10, 9), (10.2, 9.1), (10.1, 9.2), (10.2, 9.1)])
    assert structural_bias(detect_structure_shifts(flat, detect_swings(flat, 1), 1)) is Bias.NEUTRAL


def test_a_candle_cannot_break_a_pivot_the_market_had_not_yet_confirmed() -> None:
    # the high at index 1 is only « known » at index 2; a close above it at index 2 breaks it, a close at index 1 itself never does.
    candles = series(
        [{"high": 10, "low": 8, "close": 9}, {"high": 12, "low": 9, "close": 13}, {"high": 11, "low": 9, "close": 13}]
    )
    shifts = detect_structure_shifts(candles, detect_swings(candles, 1), 1)
    assert [s.shift_id for s in shifts] == ["shift-2"]


# ------------------------------------------------------------------------------------------------------ liquidity


def test_near_equal_swing_highs_cluster_into_a_pool_that_is_marked_swept_when_wicked() -> None:
    candles = series([(10, 8), (12, 9), (11, 9), (12.2, 9), (11, 8), (13, 8), (12, 8)])
    levels = detect_liquidity(candles, detect_swings(candles, 1), 0.3)
    equal_highs = next(level for level in levels if level.kind is LiquidityKind.EQUAL_HIGHS)
    assert equal_highs.price == pytest.approx(12.1, abs=0.05)
    assert equal_highs.swept_at is not None


def test_the_previous_day_high_and_low_become_todays_targets() -> None:
    candles = series(
        [(20, 18), (21, 17), (22, 16), (20, 19), (21, 18), (20, 17), (21, 18), (20, 19), (25, 24), (26, 23)],
        step_minutes=200,  # ten candles across two UTC days
    )
    levels = {level.kind: level for level in detect_liquidity(candles, detect_swings(candles, 1), 0.3)}
    assert levels[LiquidityKind.PREVIOUS_DAY_HIGH].price == 22
    assert levels[LiquidityKind.PREVIOUS_DAY_LOW].price == 16


# ------------------------------------------------------------------------------------------------------ PD arrays


def test_a_bullish_three_candle_imbalance() -> None:
    gaps = detect_fair_value_gaps(series([(10, 9), (12, 11), (14, 13)]), 0.2)
    assert len(gaps) == 1
    assert (gaps[0].direction, gaps[0].low, gaps[0].high, gaps[0].mitigated_at, gaps[0].filled_percent) == (
        Bias.BULLISH, 10, 13, None, 0
    )  # fmt: skip


def test_a_bearish_gap_is_mitigated_once_price_trades_through_it() -> None:
    gaps = detect_fair_value_gaps(series([(14, 13), (12, 11), (10, 9), (14, 12.5)]), 0.2)
    bearish = next(g for g in gaps if g.direction is Bias.BEARISH)
    assert (bearish.low, bearish.high, bearish.filled_percent) == (10, 13, 100) and bearish.mitigated_at is not None


def test_a_gap_smaller_than_the_minimum_is_ignored() -> None:
    assert detect_fair_value_gaps(series([(10, 9), (11, 10), (11.1, 10.05)]), 0.2) == []


def test_the_last_down_candle_before_a_bullish_break_is_a_bullish_order_block() -> None:
    candles = series(
        [
            {"high": 10, "low": 8, "open": 9.5, "close": 8.5},
            {"high": 11, "low": 9, "open": 9, "close": 10.5},  # swing high 11
            {"high": 10.5, "low": 9, "open": 10, "close": 9.5},  # the down candle that confirms it
            {"high": 13, "low": 10, "open": 10.2, "close": 12.5},  # close > 11 -> BOS bullish
            {"high": 11, "low": 9.5, "open": 10.5, "close": 10},  # back into the block -> mitigation
        ]
    )
    shifts = detect_structure_shifts(candles, detect_swings(candles, 1), 1)
    blocks = detect_order_blocks(candles, shifts)
    assert len(blocks) == 1
    assert (blocks[0].direction, blocks[0].high, blocks[0].low) == (Bias.BULLISH, 10.5, 9) and blocks[0].mitigated_at


# ------------------------------------------------------------------------------------------------------ scoring


def _features(**overrides: object) -> AnalysisFeatures:
    shift = StructureShift(
        shift_id="s1", symbol="XAUUSD", timeframe=Timeframe.M15, kind=StructureShiftKind.BREAK_OF_STRUCTURE,
        direction=Bias.BULLISH, broken_level=100, occurred_at=T,
    )  # fmt: skip
    fvg = FairValueGap(
        fvg_id="f1", symbol="XAUUSD", timeframe=Timeframe.M15, direction=Bias.BULLISH, high=105, low=100,
        filled_percent=0, mitigated_at=None, detected_at=T,
    )  # fmt: skip
    base: dict[str, object] = {
        "swings": [], "structure_shifts": [shift], "last_structure_shift": shift, "liquidity": [],
        "fair_value_gaps": [fvg], "order_blocks": [], "session": TradingSession.LONDON, "bias": Bias.BULLISH,
        "price_location": "discount", "recently_swept": True,
    }  # fmt: skip
    return AnalysisFeatures.model_validate(base | overrides)


WEIGHTS = DEFAULT_ANALYSIS_CONFIG.score_weights


def test_full_confluence_when_every_component_aligns() -> None:
    result = score_context(_features(), 102, True, WEIGHTS)  # price inside the FVG
    assert result.score == result.max_score == 10


def test_the_pd_array_score_is_halved_when_the_array_exists_but_price_is_outside_it() -> None:
    result = score_context(_features(), 130, True, WEIGHTS)
    assert next(c for c in result.breakdown if c.label == "PD arrays").score == 2  # Math.round(3 / 2): ties go up


def test_an_empty_neutral_context_scores_zero() -> None:
    features = _features(
        bias=Bias.NEUTRAL,
        last_structure_shift=None,
        recently_swept=False,
        fair_value_gaps=[],
        price_location="equilibrium",
    )
    assert score_context(features, 102, False, WEIGHTS).score == 0


# ------------------------------------------------------------------------------------------------------ the whole context


def test_a_coherent_bullish_context_with_a_break_and_an_unmitigated_gap() -> None:
    candles = series(
        [
            {"high": 100, "low": 98, "open": 99.5, "close": 98.2},
            {"high": 101, "low": 99, "open": 99, "close": 100.5},  # swing high 101
            {"high": 100.5, "low": 98.5, "open": 100, "close": 98.8},
            {"high": 100, "low": 97, "open": 98.5, "close": 97.2},  # swing low 97
            {"high": 99, "low": 98, "open": 97.5, "close": 98.9},
            {"high": 103, "low": 101.5, "open": 99, "close": 102.8},  # close > 101 -> BOS; gap 100..101.5
            {"high": 103.5, "low": 102, "open": 102.9, "close": 103.2},
        ]
    )
    config = DEFAULT_ANALYSIS_CONFIG.model_copy(update={"swing_lookback": 1})
    state = analyze_market_context("XAUUSD", Timeframe.M15, candles, config)
    assert state.bias is Bias.BULLISH
    assert state.last_structure_shift is not None
    assert (state.last_structure_shift.kind, state.last_structure_shift.direction) == (
        StructureShiftKind.BREAK_OF_STRUCTURE, Bias.BULLISH
    )  # fmt: skip
    assert state.max_score == 10 and state.score > 0
    assert any(g.direction is Bias.BULLISH for g in state.active_fair_value_gaps)
    assert state.computed_at == candles[-1].open_time  # at the last closed candle, never past it
    assert sum(c.score for c in state.score_breakdown) == state.score


def test_no_candles_is_a_neutral_empty_state() -> None:
    state = analyze_market_context("XAUUSD", Timeframe.M15, [])
    assert (state.bias, state.score, state.max_score, state.active_fair_value_gaps) == (Bias.NEUTRAL, 0, 10, [])
    assert state.computed_at == datetime(1970, 1, 1, tzinfo=UTC)


# ------------------------------------------------------------------------------------------------------ bias and location


SWINGS = [Swing(kind="high", price=12, index=1, time=T), Swing(kind="low", price=8, index=3, time=T)]


def test_the_directional_bias_follows_market_structure() -> None:
    assert compute_bias(Bias.BULLISH) is Bias.BULLISH and compute_bias(Bias.NEUTRAL) is Bias.NEUTRAL


def test_premium_discount_and_equilibrium_within_the_swing_range() -> None:
    assert price_location_of(11.5, SWINGS) == "premium"
    assert price_location_of(8.5, SWINGS) == "discount"
    assert price_location_of(10, SWINGS) == "equilibrium"
    assert price_location_of(10, SWINGS[:1]) == "equilibrium"  # a side of the range is missing


# ------------------------------------------------------------------------------------------------------ ATR


def test_atr_needs_two_candles_and_a_positive_period() -> None:
    assert average_true_range([], 14) == 0
    assert average_true_range(series([(10, 9)]), 14) == 0
    assert average_true_range(series([(10, 9), (11, 10)]), 0) == 0


def test_atr_is_the_plain_mean_when_there_are_fewer_true_ranges_than_the_period() -> None:
    assert average_true_range(series([(10, 8), (12, 10)]), 14) == pytest.approx(3, abs=1e-6)


def test_atr_smooths_with_wilders_recursion_past_the_seed_period() -> None:
    flat = series([(10 + i, 8 + i) for i in range(20)])
    assert average_true_range(flat, 14) > 0
    constant = series([(10, 8)] * 30)
    assert average_true_range(constant, 14) == 2  # a constant true range is its own average whatever the smoothing


def test_atr_ignores_candles_after_the_slice_it_is_given() -> None:
    base = series([(10 + (i % 3), 8 + (i % 3)) for i in range(30)])
    assert average_true_range(base[:20], 14) == average_true_range(list(base[:20]), 14)


# ------------------------------------------------------------------------------------------------------ aggregation


def test_m1_candles_merge_into_one_h1_bucket() -> None:
    source = [
        candle_at(0, 1.101, 1.099, open=1.1, close=1.1005, step_minutes=1, timeframe=Timeframe.M1),
        candle_at(1, 1.103, 1.1, open=1.1005, close=1.102, step_minutes=1, timeframe=Timeframe.M1),
        candle_at(2, 1.102, 1.098, open=1.102, close=1.099, step_minutes=1, timeframe=Timeframe.M1),
    ]
    (h1,) = aggregate_candles(source, Timeframe.M1, Timeframe.H1)
    assert (h1.timeframe, h1.open_time) == (Timeframe.H1, datetime(2026, 1, 5, 0, 0, tzinfo=UTC))
    assert (h1.open, h1.close, h1.high, h1.low, h1.volume) == (1.1, 1.099, 1.103, 1.098, 300)
    assert h1.closed is False  # only 3 of the 60 expected members are there


def test_a_new_bucket_starts_when_the_open_time_crosses_the_boundary() -> None:
    source = [
        candle_at(59, 1.101, 1.099, step_minutes=1, timeframe=Timeframe.M1),
        candle_at(60, 1.105, 1.104, step_minutes=1, timeframe=Timeframe.M1),
    ]
    buckets = aggregate_candles(source, Timeframe.M1, Timeframe.H1)
    assert [b.open_time.hour for b in buckets] == [0, 1]


def test_a_bucket_is_closed_only_when_complete_and_its_last_member_is_closed() -> None:
    full = [candle_at(i, 1.1 + i * 0.0001, 1.1, step_minutes=1, timeframe=Timeframe.M1) for i in range(60)]
    assert aggregate_candles(full, Timeframe.M1, Timeframe.H1)[0].closed is True
    forming = [*full[:59], full[59].model_copy(update={"closed": False})]
    assert aggregate_candles(forming, Timeframe.M1, Timeframe.H1)[0].closed is False
    assert aggregate_candles([], Timeframe.M1, Timeframe.H1) == []


# ------------------------------------------------------------------------------------------------------ sessions


def _at(hour: int) -> datetime:
    return datetime(2026, 1, 5, hour, tzinfo=UTC)


def test_utc_hours_map_to_sessions_including_the_window_that_wraps_midnight() -> None:
    expected = {1: "asia", 8: "london", 13: "new_york_am", 17: "new_york_pm", 21: "off_session"}
    for hour, session in expected.items():
        assert session_for_timestamp(_at(hour), DEFAULT_SESSION_WINDOWS).value == session, hour


def test_a_session_is_enabled_as_its_window_says() -> None:
    assert session_enabled(TradingSession.LONDON, DEFAULT_SESSION_WINDOWS) is True
    assert session_enabled(TradingSession.ASIA, DEFAULT_SESSION_WINDOWS) is False


# ------------------------------------------------------------------------------------------------------ the original's two decimals


FIVE_DIGITS = series(
    [(1.0810, 1.0800), (1.0831, 1.0805), (1.0815, 1.0802), (1.0829, 1.0806), (1.0812, 1.0801), (1.0840, 1.0805)],
    symbol="EURUSDm",
    timeframe=Timeframe.M5,
)  # two swing highs a hair apart (1.0831 and 1.0829), then a wick above them


def test_a_level_keeps_two_decimals_like_the_original_which_is_golds_not_a_pairs() -> None:
    swings = detect_swings(FIVE_DIGITS, 1)
    original = next(
        level for level in detect_liquidity(FIVE_DIGITS, swings, 0.0005) if level.kind is LiquidityKind.EQUAL_HIGHS
    )
    assert original.price == 1.08  # the cluster is at 1.0830: up to 50 pips lost on a five-digit pair


def test_the_precision_of_a_level_is_a_parameter_and_the_sweep_scan_never_uses_the_rounded_price() -> None:
    swings = detect_swings(FIVE_DIGITS, 1)
    original = next(
        level for level in detect_liquidity(FIVE_DIGITS, swings, 0.0005) if level.kind is LiquidityKind.EQUAL_HIGHS
    )
    precise = next(
        level
        for level in detect_liquidity(FIVE_DIGITS, swings, 0.0005, price_decimals=5)
        if level.kind is LiquidityKind.EQUAL_HIGHS
    )
    assert precise.price == pytest.approx(1.0830)
    assert original.swept_at == precise.swept_at == FIVE_DIGITS[5].open_time  # swept by the wick to 1.0840, either way
