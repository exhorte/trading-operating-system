"""Strategy S01, stated as readable cases (the TypeScript tests of ``lib/setup``, carried over). The golden vectors prove the port computes
what the original did; these say what that is, step by step and then end to end."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.support.candles import Bar, series
from tests.unit.domain.s01.scenario import (
    BEARISH_HTF,
    BULLISH_HTF,
    CONTEXT,
    H1_PREMIUM,
    REACTION,
    base_input,
)
from trading_os.domain.market.analysis.models import FairValueGap, LiquidityKind, LiquidityLevel, OrderBlock
from trading_os.domain.market.analysis.swings import detect_swings
from trading_os.domain.market.sessions import DEFAULT_SESSION_WINDOWS
from trading_os.domain.primitives import Bias, Side, Timeframe
from trading_os.domain.strategy.s01 import BlockedOutcome, ProposedOutcome, SetupStage, evaluate_setup, propose_setup
from trading_os.domain.strategy.s01.bias import daily_bias
from trading_os.domain.strategy.s01.dealing_range import DealingRange, last_dealing_range, location_in_range
from trading_os.domain.strategy.s01.displacement import DisplacementConfig, DisplacementEvent, detect_displacement
from trading_os.domain.strategy.s01.gates import ViabilityGateInput, evaluate_viability_gates
from trading_os.domain.strategy.s01.liquidity import liquidity_pool, opposing_target, sweep_trigger_candidate
from trading_os.domain.strategy.s01.poi import PointOfInterest, is_invalidated_by_ce, point_of_interest_for
from trading_os.domain.strategy.s01.preconditions import is_in_killzone, is_past_ny_lunch
from trading_os.domain.strategy.s01.reconciliation import (
    AgreementClass,
    AgreementProposal,
    AgreementTrade,
    reconcile,
)
from trading_os.domain.strategy.s01.stop import compute_stop_loss
from trading_os.domain.strategy.s01.sweep import SweepLevel, detect_sweep


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# ------------------------------------------------------------------------------------------------------ step 1 — bias

NO_STRUCTURE = series([{"high": 10, "low": 9, "close": 9.5}] * 4)


def test_the_daily_bias_is_bullish_when_h4_and_d1_agree() -> None:
    assert daily_bias(BULLISH_HTF, BULLISH_HTF, 1) is Bias.BULLISH


def test_the_daily_bias_is_neutral_when_they_disagree_or_either_has_no_structure() -> None:
    assert daily_bias(BULLISH_HTF, BEARISH_HTF, 1) is Bias.NEUTRAL
    assert daily_bias(BULLISH_HTF, NO_STRUCTURE, 1) is Bias.NEUTRAL
    assert daily_bias(NO_STRUCTURE, NO_STRUCTURE, 1) is Bias.NEUTRAL


# ------------------------------------------------------------------------------------------------------ step 2 — dealing range


def test_no_range_with_fewer_than_two_swings() -> None:
    assert last_dealing_range(NO_STRUCTURE[:3], 1) is None


def test_the_range_is_the_last_swing_and_the_nearest_earlier_opposite_one() -> None:
    candles = series(
        [
            {"high": 10, "low": 9, "close": 9.5},
            {"high": 9, "low": 8, "close": 8.5},  # swing low 8
            {"high": 10, "low": 9, "close": 9.5},
            {"high": 12, "low": 10, "close": 11},  # swing high 12
            {"high": 10, "low": 9, "close": 9.5},
        ]
    )
    assert last_dealing_range(candles, 1) == DealingRange(external_high=12, external_low=8, equilibrium=10)


def test_the_location_is_a_strict_half_split_with_no_neutral_band() -> None:
    dealing = DealingRange(external_high=12, external_low=8, equilibrium=10)
    assert location_in_range(9, dealing) == "discount" and location_in_range(11, dealing) == "premium"
    assert (location_in_range(10, dealing), location_in_range(10.01, dealing), location_in_range(9.99, dealing)) == (
        "equilibrium", "premium", "discount"
    )  # fmt: skip


# ------------------------------------------------------------------------------------------------------ step 3 — liquidity

ASIA_CANDLES = series(
    [(1.105, 1.101), (1.106, 1.1005), (1.1055, 1.102), (1.107, 1.099), (1.108, 1.1), (1.104, 1.101), (1.103, 1.1015),
     (1.1035, 1.102), (1.104, 1.1015), (1.1045, 1.1018)],
    symbol="EURUSD", step_minutes=60,
)  # fmt: skip


def test_the_asia_levels_are_those_of_the_most_recent_contiguous_asia_block() -> None:
    pool = liquidity_pool(ASIA_CANDLES, [], 0.3, DEFAULT_SESSION_WINDOWS)
    by_kind = {level.kind: level for level in pool}
    assert by_kind[LiquidityKind.SESSION_HIGH].price == pytest.approx(1.108)
    assert by_kind[LiquidityKind.SESSION_LOW].price == pytest.approx(1.099)


def test_an_asia_level_is_swept_once_a_later_candle_wicks_beyond_it() -> None:
    swept = [*ASIA_CANDLES[:7], *series([(1.109, 1.102)], symbol="EURUSD", step_minutes=60)]
    swept[-1] = swept[-1].model_copy(update={"open_time": ASIA_CANDLES[7].open_time})
    high = next(
        level
        for level in liquidity_pool(swept, [], 0.3, DEFAULT_SESSION_WINDOWS)
        if level.kind is LiquidityKind.SESSION_HIGH
    )
    assert high.swept_at is not None


def _level(kind: LiquidityKind, price: float, swept: bool = False) -> LiquidityLevel:
    return LiquidityLevel(
        level_id=kind.value, symbol="EURUSD", timeframe=Timeframe.M1, kind=kind, price=price,
        swept_at=utc("2026-01-05T01:00:00Z") if swept else None, detected_at=utc("2026-01-05T00:00:00Z"),
    )  # fmt: skip


POOL = [
    _level(LiquidityKind.PREVIOUS_DAY_HIGH, 1.11),
    _level(LiquidityKind.EQUAL_HIGHS, 1.105),
    _level(LiquidityKind.PREVIOUS_DAY_LOW, 1.09),
    _level(LiquidityKind.EQUAL_LOWS, 1.095, swept=True),
]


def test_a_buy_targets_the_nearest_unswept_high_side_level() -> None:
    target = opposing_target(POOL, Side.BUY, 1.1)
    assert target is not None and (target.kind, target.price) == (LiquidityKind.EQUAL_HIGHS, 1.105)


def test_a_buy_sweep_trigger_ignores_levels_already_swept() -> None:
    trigger = sweep_trigger_candidate(POOL, Side.BUY, 1.1)  # equal lows 1.095 is nearer but swept
    assert trigger is not None and (trigger.kind, trigger.price) == (LiquidityKind.PREVIOUS_DAY_LOW, 1.09)


def test_no_candidate_means_none() -> None:
    swept = [level.model_copy(update={"swept_at": utc("2026-01-05T01:00:00Z")}) for level in POOL]
    assert opposing_target(swept, Side.BUY, 1.1) is None and sweep_trigger_candidate(swept, Side.SELL, 1.1) is None


# ------------------------------------------------------------------------------------------------------ step 4 — sweep

LOW_LEVEL = SweepLevel(kind=LiquidityKind.PREVIOUS_DAY_LOW, price=1.1)


def test_a_buy_side_sweep_breaches_the_level_and_reclaims_it_in_the_same_candle() -> None:
    candles = series([{"high": 1.102, "low": 1.101, "close": 1.1015}, {"high": 1.103, "low": 1.098, "close": 1.1012}])
    sweep = detect_sweep(candles, LOW_LEVEL, Side.BUY)
    assert sweep is not None and sweep.wick_extreme == 1.098 and sweep.swept_at == candles[1].open_time


def test_a_sell_side_sweep_is_the_mirror() -> None:
    level = SweepLevel(kind=LiquidityKind.PREVIOUS_DAY_HIGH, price=1.1)
    candles = series([{"high": 1.099, "low": 1.097, "close": 1.098}, {"high": 1.103, "low": 1.098, "close": 1.0985}])
    sweep = detect_sweep(candles, level, Side.SELL)
    assert sweep is not None and sweep.wick_extreme == 1.103


def test_a_breach_without_a_reclaim_is_a_cassure_and_the_setup_is_abandoned_not_deferred() -> None:
    candles = series(
        [
            {"high": 1.103, "low": 1.098, "close": 1.099},  # low < level but the close is below it too: no reclaim
            {"high": 1.101, "low": 1.0995, "close": 1.1005},  # this bar WOULD reclaim — and must never be reached
        ]
    )
    assert detect_sweep(candles, LOW_LEVEL, Side.BUY) is None


def test_a_level_that_is_never_touched_is_no_sweep() -> None:
    candles = series([{"high": 1.103, "low": 1.101, "close": 1.102}, {"high": 1.104, "low": 1.1015, "close": 1.103}])
    assert detect_sweep(candles, LOW_LEVEL, Side.BUY) is None


# ------------------------------------------------------------------------------------------------------ step 5 — displacement

DISPLACEMENT = DisplacementConfig(atr_period=14, min_body_atr_multiple=1.5, min_fvg_size=0.2)
RUN_UP: list[Bar] = [
    {"high": 101, "low": 100, "open": 100.5, "close": 100.5},
    {"high": 102, "low": 101, "open": 101.5, "close": 101.5},
    {"high": 103, "low": 102, "open": 102.5, "close": 102.5},
]


def test_a_body_break_with_a_big_body_and_an_unfilled_fvg_is_a_displacement() -> None:
    candles = series([*RUN_UP, {"high": 110.2, "low": 102.8, "open": 103, "close": 110}])
    found = detect_displacement(candles, Side.BUY, 103, DISPLACEMENT)
    assert found is not None and found.occurred_at == candles[3].open_time
    assert found.fair_value_gap.direction is Bias.BULLISH and found.fair_value_gap.mitigated_at is None


def test_a_wick_through_the_swing_counts_for_nothing() -> None:
    candles = series([*RUN_UP, {"high": 104, "low": 102.5, "open": 102.5, "close": 102.8}])  # the body stays below 103
    assert detect_displacement(candles, Side.BUY, 103, DISPLACEMENT) is None


def test_a_break_with_a_body_too_small_for_the_atr_is_not_a_displacement() -> None:
    candles = series([*RUN_UP, {"high": 103.3, "low": 102.9, "open": 103.0, "close": 103.1}])
    assert detect_displacement(candles, Side.BUY, 103, DISPLACEMENT) is None


# ------------------------------------------------------------------------------------------------------ step 6 — point of interest


def _displacement(mitigated_at: datetime | None) -> DisplacementEvent:
    gap = FairValueGap(
        fvg_id="fvg-3", symbol="EURUSD", timeframe=Timeframe.M1, direction=Bias.BULLISH, high=102.8, low=102,
        filled_percent=100 if mitigated_at else 0, mitigated_at=mitigated_at, detected_at=utc("2026-01-05T00:03:00Z"),
    )  # fmt: skip
    return DisplacementEvent(
        occurred_at=utc("2026-01-05T00:03:00Z"), broken_swing_price=103, fair_value_gap=gap, body_size=7, atr=3.5
    )


def test_the_poi_is_the_fvg_while_it_is_unmitigated() -> None:
    poi = point_of_interest_for(_displacement(None), [], Side.BUY)
    assert poi is not None and (poi.kind, poi.high, poi.low) == ("fvg", 102.8, 102)
    assert poi.ce == pytest.approx(102.4)


def test_the_poi_falls_back_to_the_origin_order_block_when_the_fvg_is_already_mitigated() -> None:
    block = OrderBlock(
        order_block_id="ob-1", symbol="EURUSD", timeframe=Timeframe.M1, direction=Bias.BULLISH, high=101, low=100.5,
        mitigated_at=None, detected_at=utc("2026-01-05T00:00:00Z"),
    )  # fmt: skip
    poi = point_of_interest_for(_displacement(utc("2026-01-05T00:04:00Z")), [block], Side.BUY)
    assert poi is not None and (poi.kind, poi.high, poi.low) == ("order_block", 101, 100.5)
    assert poi.ce == pytest.approx(100.75)


def test_no_poi_when_the_fvg_is_mitigated_and_there_is_no_usable_block() -> None:
    assert point_of_interest_for(_displacement(utc("2026-01-05T00:04:00Z")), [], Side.BUY) is None


POI = PointOfInterest(kind="fvg", high=102.8, low=102, ce=102.4, formed_at=utc("2026-01-05T00:03:00Z"))


def test_a_body_closing_beyond_the_ce_invalidates_the_setup() -> None:
    candles = series([{"high": 102.6, "low": 102.3, "close": 102.5}, {"high": 102.4, "low": 102.1, "close": 102.2}])
    assert is_invalidated_by_ce(POI, Side.BUY, candles) is True


def test_a_setup_whose_bodies_stay_on_the_right_side_of_the_ce_stands() -> None:
    candles = series([{"high": 102.7, "low": 102.45, "close": 102.5}, {"high": 102.6, "low": 102.41, "close": 102.45}])
    assert is_invalidated_by_ce(POI, Side.BUY, candles) is False


# ------------------------------------------------------------------------------------------------------ step 7 — stop


def test_a_buy_stop_sits_below_the_wick_extreme_minus_the_buffer() -> None:
    stop = compute_stop_loss(Side.BUY, 1.098, 0.0002, 1.1024)
    assert stop is not None and stop.price == pytest.approx(1.0978) and stop.distance == pytest.approx(1.1024 - 1.0978)


def test_a_sell_stop_sits_above_the_wick_extreme_plus_the_buffer() -> None:
    stop = compute_stop_loss(Side.SELL, 1.102, 0.0002, 1.0976)
    assert stop is not None and stop.price == pytest.approx(1.1022)


def test_a_stop_wider_than_the_ceiling_is_refused_and_without_a_ceiling_nothing_is() -> None:
    assert compute_stop_loss(Side.BUY, 1.09, 0.0002, 1.1024, 0.005) is None
    assert compute_stop_loss(Side.BUY, 1.09, 0.0002, 1.1024) is not None


# ------------------------------------------------------------------------------------------------------ step 8 — gates

SPREAD, COMMISSION = 0.00007, 0.00002  # the order of magnitude of S01's own EURUSD table


def _gate(**changes: object) -> ViabilityGateInput:
    data: dict[str, object] = {
        "entry_price": 1.1024, "stop_distance": 0.0003, "target_price": 1.1124, "side": Side.BUY, "spread": SPREAD,
        "commission": COMMISSION, "cost_threshold": 0.25, "min_risk_reward": 3,
    }  # fmt: skip
    return ViabilityGateInput.model_validate(data | changes)


def test_the_cost_gate_refuses_a_tight_stop() -> None:
    result = evaluate_viability_gates(_gate())  # SL 3 pips -> c ~= 0.30
    assert result.cost_ratio == pytest.approx(0.3, abs=0.005) and not result.passed
    assert result.reason == "porte de coût: c=0.300 > seuil 0.25"


def test_a_wider_stop_passes_both_gates() -> None:
    result = evaluate_viability_gates(_gate(stop_distance=0.0007, target_price=1.1234))  # SL 7 pips -> c ~= 0.13
    assert result.cost_ratio == pytest.approx(0.13, abs=0.005) and result.passed and result.reason is None


def test_the_rr_gate_refuses_when_the_real_ratio_after_cost_is_below_the_minimum() -> None:
    result = evaluate_viability_gates(
        _gate(entry_price=1.1, stop_distance=0.001, target_price=1.102, spread=0.00002, commission=0.00001)
    )
    assert not result.passed and result.reason is not None and result.reason.startswith("porte R:R: ")
    assert result.reason.endswith("< 3")  # (a whole number prints without a decimal point, like the original)


# ------------------------------------------------------------------------------------------------------ calendar


def test_the_london_killzone_in_winter_is_utc_minus_five() -> None:
    assert is_in_killzone(utc("2026-01-15T08:00:00Z")) is True  # 03:00 NY


def test_the_ny_am_killzone_in_summer_handles_dst() -> None:
    assert is_in_killzone(utc("2026-06-15T12:00:00Z")) is True  # 08:00 NY (EDT)


def test_between_and_outside_the_killzones() -> None:
    assert is_in_killzone(utc("2026-01-15T11:00:00Z")) is False  # 06:00 NY
    assert is_in_killzone(utc("2026-01-15T23:00:00Z")) is False


def test_no_new_position_from_noon_new_york() -> None:
    assert (
        is_past_ny_lunch(utc("2026-01-15T16:59:00Z")) is False and is_past_ny_lunch(utc("2026-01-15T17:00:00Z")) is True
    )
    assert (
        is_past_ny_lunch(utc("2026-06-15T16:00:00Z")) is True and is_past_ny_lunch(utc("2026-06-15T15:59:00Z")) is False
    )


# ------------------------------------------------------------------------------------------------------ step 9 — the sequence


def test_a_complete_buy_proposal_when_every_step_passes() -> None:
    proposal = propose_setup(base_input())
    assert proposal is not None
    assert (proposal.symbol, proposal.side, proposal.swept_level_kind, proposal.swept_level_price, proposal.take_profit) == (
        "EURUSD", Side.BUY, LiquidityKind.EQUAL_LOWS, 99, 105
    )  # fmt: skip
    assert proposal.entry_price == pytest.approx(99.85) and proposal.stop_loss == pytest.approx(98.65)
    assert proposal.cost_ratio == pytest.approx(0.1, abs=0.005) and proposal.risk_reward_ratio >= 3
    assert (
        proposal.proposal_id == "setup-EURUSD-2026-01-05T07:17:00.000Z"
    )  # the id the original wrote, millisecond and all


def test_disagreeing_timeframes_stop_the_sequence_at_the_bias() -> None:
    outcome = evaluate_setup(base_input(d1_candles=BEARISH_HTF))
    assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.BIAS
    assert propose_setup(base_input(d1_candles=BEARISH_HTF)) is None


def test_price_on_the_wrong_side_of_the_range_stops_it_at_the_range_location() -> None:
    outcome = evaluate_setup(base_input(h1_candles=H1_PREMIUM))
    assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.RANGE_LOCATION
    assert outcome.detail == "price is premium, need discount for a buy"


def test_no_candidate_level_stops_it_at_the_liquidity_map() -> None:
    outcome = evaluate_setup(base_input(context_candles=CONTEXT[:2]))
    assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.LIQUIDITY


def test_a_level_never_touched_stops_it_at_the_sweep() -> None:
    quiet = [c.model_copy(update={"low": 99.5, "high": max(c.high, 99.6)}) for c in REACTION]
    outcome = evaluate_setup(base_input(reaction_candles=quiet))
    assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.SWEEP


def test_a_reclaim_that_never_breaks_out_stops_it_at_the_displacement() -> None:
    calm = [REACTION[0], *(c.model_copy(update={"close": 99.5, "open": 99.4, "high": 99.6}) for c in REACTION[1:])]
    outcome = evaluate_setup(base_input(reaction_candles=calm))
    assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.DISPLACEMENT


def test_a_stop_over_the_ceiling_stops_it_at_the_stop() -> None:
    outcome = evaluate_setup(base_input(max_stop_distance=0.5))
    assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.STOP


def test_an_expensive_round_trip_stops_it_at_the_gates_with_the_original_wording() -> None:
    outcome = evaluate_setup(base_input(spread=5, commission=5))
    assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.GATES
    assert outcome.detail.startswith("porte de coût: c=") and outcome.detail.endswith("> seuil 0.25")
    assert propose_setup(base_input(spread=5, commission=5)) is None


def test_the_success_path_reports_proposed() -> None:
    assert isinstance(evaluate_setup(base_input()), ProposedOutcome)


# ------------------------------------------------------------------------------------------------------ agreement


def _proposal(detected: str, symbol: str = "EURUSDm", side: Side = Side.BUY) -> AgreementProposal:
    return AgreementProposal(symbol=symbol, side=side, detected_at=utc(detected))


def _trade(position: str, opened: str, symbol: str = "EURUSDm", side: Side = Side.BUY) -> AgreementTrade:
    return AgreementTrade(broker_position_id=position, symbol=symbol, side=side, opened_at=utc(opened))


def test_a_trade_within_tolerance_of_a_proposal_is_the_same_trade() -> None:
    (row,) = reconcile([_proposal("2026-01-05T10:00:00Z")], [_trade("p1", "2026-01-05T10:03:00Z")], 5)
    assert row.agreement is AgreementClass.PROPOSED_AND_TAKEN and row.broker_position_id == "p1"


def test_a_proposal_nobody_took_was_refused() -> None:
    (row,) = reconcile([_proposal("2026-01-05T10:00:00Z")], [], 5)
    assert row.agreement is AgreementClass.PROPOSED_AND_REFUSED and row.trade_opened_at is None


def test_a_trade_nobody_proposed_is_the_class_that_matters_most() -> None:
    (row,) = reconcile([], [_trade("p1", "2026-01-05T10:00:00Z", "GBPUSDm", Side.SELL)], 5)
    assert row.agreement is AgreementClass.TAKEN_WITHOUT_PROPOSAL and row.proposal_detected_at is None


def test_nothing_matches_across_symbols_sides_or_outside_the_tolerance() -> None:
    rows = reconcile(
        [_proposal("2026-01-05T10:00:00Z")],
        [
            _trade("a", "2026-01-05T10:01:00Z", symbol="GBPUSDm"),
            _trade("b", "2026-01-05T10:01:00Z", side=Side.SELL),
            _trade("c", "2026-01-05T10:10:00Z"),
        ],
        5,
    )
    assert [r.agreement for r in rows].count(AgreementClass.PROPOSED_AND_TAKEN) == 0
    assert [r.agreement for r in rows].count(AgreementClass.TAKEN_WITHOUT_PROPOSAL) == 3


def test_a_trade_goes_to_the_nearest_proposal_and_only_once() -> None:
    rows = reconcile(
        [_proposal("2026-01-05T10:00:00Z"), _proposal("2026-01-05T10:01:00Z")],
        [_trade("p1", "2026-01-05T10:01:30Z")],
        5,
    )
    taken = [r for r in rows if r.agreement is AgreementClass.PROPOSED_AND_TAKEN]
    assert len(taken) == 1 and taken[0].proposal_detected_at == datetime(2026, 1, 5, 10, 1, tzinfo=UTC)
    assert [r.agreement for r in rows].count(AgreementClass.PROPOSED_AND_REFUSED) == 1
    assert [r.agreement for r in rows].count(AgreementClass.TAKEN_WITHOUT_PROPOSAL) == 0


# ------------------------------------------------------------------------------------------------------ the original's two decimals


def test_the_levels_of_the_pool_keep_two_decimals_unless_told_otherwise() -> None:
    candles = series(
        [(1.0810, 1.0800), (1.0831, 1.0805), (1.0815, 1.0802), (1.0829, 1.0806), (1.0812, 1.0801), (1.0840, 1.0805)],
        symbol="EURUSDm", timeframe=Timeframe.M5,
    )  # fmt: skip
    swings = detect_swings(candles, 1)
    rounded = liquidity_pool(candles, swings, 0.0005, DEFAULT_SESSION_WINDOWS)
    exact = liquidity_pool(candles, swings, 0.0005, DEFAULT_SESSION_WINDOWS, price_decimals=5)
    highs = {
        pool_name: next(lv for lv in pool if lv.kind is LiquidityKind.EQUAL_HIGHS)
        for pool_name, pool in (("rounded", rounded), ("exact", exact))
    }
    assert highs["rounded"].price == 1.08 and highs["exact"].price == pytest.approx(1.083)


def test_the_proposal_input_carries_the_precision_to_the_pool() -> None:
    assert base_input().level_decimals == 2 and base_input(level_decimals=5).level_decimals == 5
    assert (
        propose_setup(base_input(level_decimals=5)) is not None
    )  # the reference scenario's prices have two decimals: same result
