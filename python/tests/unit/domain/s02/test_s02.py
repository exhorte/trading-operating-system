"""S02 (ADR 0024, amended): the pipeline of S01 with a bias read on H4 + H1, the dealing range and the liquidity map on the 15-minute
series, a zone that must sit on the right side of the 50 % line, a target past it, and a limit order at the edge of the FVG (notes N5, N6).

The 15-minute series of these tests is the scenario's candle list used as a stand-in: the detectors only read highs, lows and closes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.unit.domain.s01.scenario import (
    BEARISH_HTF,
    BULLISH_HTF,
    CONTEXT,
    H1_BULLISH_DISCOUNT,
    H1_DISCOUNT,
    base_input,
)
from trading_os.domain.primitives import Bias, Side
from trading_os.domain.strategy.s01 import BlockedOutcome, ProposedOutcome, SetupStage, evaluate_setup
from trading_os.domain.strategy.s01.dealing_range import DealingRange
from trading_os.domain.strategy.s01.poi import PointOfInterest
from trading_os.domain.strategy.s01.proposal import S01_VARIANT, entry_in_poi
from trading_os.domain.strategy.s02 import S02Config, evaluate_setup_s02, s02_variant

CONFIG = S02Config()
SPREAD = 0.1  # the scenario's spread (base_input)
EASY = {"min_risk_reward": 0.5, "cost_threshold": 1.0}  # let the gates pass so only the entry level moves


def s02_input(**changes: object):  # type: ignore[no-untyped-def]
    return base_input(h1_candles=H1_BULLISH_DISCOUNT, map_candles=CONTEXT, **changes)


def proposal(outcome: object):  # type: ignore[no-untyped-def]
    assert isinstance(outcome, ProposedOutcome), outcome
    return outcome.proposal


class TestBias:
    def test_s02_reads_h4_and_h1_where_s01_reads_h4_and_d1(self) -> None:
        # the scenario's 1H series has no confirmed structure: S01 (D1 bullish) goes on, S02 (H1 neutral) stops at the bias
        s01 = evaluate_setup(base_input())
        assert isinstance(s01, ProposedOutcome)
        s02 = evaluate_setup_s02(base_input(map_candles=CONTEXT), CONFIG)
        assert isinstance(s02, BlockedOutcome) and s02.stage is SetupStage.BIAS and "H4/H1" in s02.detail

    def test_s02_does_not_need_the_daily_candles(self) -> None:
        assert isinstance(evaluate_setup_s02(s02_input(d1_candles=[]), CONFIG), ProposedOutcome)

    def test_h4_and_h1_must_agree(self) -> None:
        bearish_h4 = evaluate_setup_s02(s02_input(h4_candles=BEARISH_HTF), CONFIG)
        assert isinstance(bearish_h4, BlockedOutcome) and bearish_h4.stage is SetupStage.BIAS
        neutral_h1 = evaluate_setup_s02(base_input(h1_candles=H1_DISCOUNT, map_candles=CONTEXT), CONFIG)
        assert isinstance(neutral_h1, BlockedOutcome) and neutral_h1.stage is SetupStage.BIAS


class TestTheFifteenMinuteMap:
    def test_without_the_map_there_is_no_dealing_range(self) -> None:
        outcome = evaluate_setup_s02(base_input(h1_candles=H1_BULLISH_DISCOUNT), CONFIG)
        assert (
            isinstance(outcome, BlockedOutcome)
            and outcome.stage is SetupStage.DEALING_RANGE
            and "15m" in outcome.detail
        )

    def test_the_1h_series_is_not_where_the_range_is_read(self) -> None:
        # the 1H candles hold a perfectly good range; S02 ignores it and says it is looking at the 15-minute one
        assert isinstance(evaluate_setup(base_input(h1_candles=H1_BULLISH_DISCOUNT)), ProposedOutcome)
        outcome = evaluate_setup_s02(base_input(h1_candles=H1_BULLISH_DISCOUNT, map_candles=CONTEXT[:1]), CONFIG)
        assert isinstance(outcome, BlockedOutcome) and "15m" in outcome.detail

    def test_s01_keeps_reading_the_1h_series(self) -> None:
        outcome = evaluate_setup(base_input(h1_candles=[]))
        assert isinstance(outcome, BlockedOutcome) and "1H" in outcome.detail


class TestProposal:
    def test_a_complete_sequence_rests_a_limit_at_the_edge_of_the_fvg_plus_the_spread(self) -> None:
        s02 = proposal(evaluate_setup_s02(s02_input(), CONFIG))
        s01 = proposal(evaluate_setup(base_input()))
        assert s02.side is Side.BUY
        assert s01.entry_price == pytest.approx(99.85)  # S01: the CE of the FVG (99.7 – 100.0)
        assert s02.entry_price == pytest.approx(
            100.0 + SPREAD
        )  # N5/N6: the edge price reaches first, one spread above for the ask
        assert (s02.stop_loss, s02.take_profit) == (s01.stop_loss, s01.take_profit)

    def test_its_identifier_cannot_collide_with_s01s_on_the_same_displacement(self) -> None:
        s02 = proposal(evaluate_setup_s02(s02_input(), CONFIG))
        s01 = proposal(evaluate_setup(base_input()))
        assert s02.proposal_id.startswith("setup-s02-") and s01.proposal_id.startswith("setup-EURUSD-")
        assert s02.proposal_id != s01.proposal_id and s02.detected_at == s01.detected_at

    def test_the_entry_fraction_moves_the_limit_inside_the_zone(self) -> None:
        def entry(fraction: float) -> float:
            return proposal(evaluate_setup_s02(s02_input(**EASY), S02Config(entry_fraction=fraction))).entry_price

        near, ce, far = entry(0.0), entry(0.5), entry(1.0)
        assert near > ce > far  # a buy: the edge price reaches first is the top of the zone


class TestTheZoneAndTheTarget:
    @staticmethod
    def with_range(monkeypatch: pytest.MonkeyPatch, equilibrium: float) -> None:
        monkeypatch.setattr(
            "trading_os.domain.strategy.s01.proposal.last_dealing_range",
            lambda candles, lookback: DealingRange(external_high=110.0, external_low=90.0, equilibrium=equilibrium),
        )

    def test_a_buy_zone_in_premium_is_refused_even_when_the_price_is_in_discount(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # N5 : « pas de vente d'un FVG situé en Discount » (and its mirror). The zone's CE is 99.85; the 50 % line is 99.0 here.
        self.with_range(monkeypatch, equilibrium=99.0)
        outcome = evaluate_setup_s02(s02_input(), CONFIG)
        assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.RANGE_LOCATION
        assert "zone of interest is in premium" in outcome.detail

    def test_s01_still_judges_the_price_not_the_zone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.with_range(monkeypatch, equilibrium=101.0)  # the last close (100.3) is in discount: S01 goes on
        assert isinstance(evaluate_setup(base_input()), ProposedOutcome)

    def test_a_target_short_of_the_50_percent_line_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # the zone is in discount (CE 99.85 < 106) but the target, 105, is not past the 50 % line: N5 « sous cette ligne »
        self.with_range(monkeypatch, equilibrium=106.0)
        outcome = evaluate_setup_s02(s02_input(), CONFIG)
        assert isinstance(outcome, BlockedOutcome) and outcome.stage is SetupStage.GATES and "50 %" in outcome.detail


class TestEntryInZone:
    POI = PointOfInterest(kind="fvg", high=1.1010, low=1.1000, ce=1.1005, formed_at=datetime(2026, 11, 2, tzinfo=UTC))

    def test_the_ce_is_returned_exactly(self) -> None:
        assert entry_in_poi(self.POI, Side.BUY, 0.5) == self.POI.ce
        assert entry_in_poi(self.POI, Side.SELL, 0.5) == self.POI.ce

    def test_a_buy_goes_down_the_zone_and_a_sell_goes_up_it(self) -> None:
        assert entry_in_poi(self.POI, Side.BUY, 0.0) == pytest.approx(1.1010)
        assert entry_in_poi(self.POI, Side.BUY, 1.0) == pytest.approx(1.1000)
        assert entry_in_poi(self.POI, Side.SELL, 0.0) == pytest.approx(1.1000)
        assert entry_in_poi(self.POI, Side.SELL, 1.0) == pytest.approx(1.1010)
        assert entry_in_poi(self.POI, Side.BUY, 0.25) == pytest.approx(1.10075)


class TestConfig:
    def test_the_defaults_are_the_notes_where_they_speak_and_s01s_elsewhere(self) -> None:
        assert CONFIG.entry_fraction == 0.0  # N5: the edge of the FVG
        assert CONFIG.symbols == ("EURUSD",) and CONFIG.min_risk_reward == 3.0 and CONFIG.atr_period == 14

    def test_the_variant_carries_every_rule_it_changes(self) -> None:
        variant = s02_variant(S02Config(entry_fraction=0.7))
        assert variant.id_prefix == "setup-s02" and variant.entry_fraction == 0.7 and variant is not S01_VARIANT
        assert variant.use_map_timeframe and variant.poi_location and variant.target_beyond_equilibrium
        assert variant.entry_spread_offset

    def test_s01_changes_none_of_it(self) -> None:
        v = S01_VARIANT
        assert v.id_prefix == "setup" and v.entry_fraction == 0.5
        assert not (v.use_map_timeframe or v.poi_location or v.target_beyond_equilibrium or v.entry_spread_offset)

    def test_the_fraction_is_inside_the_zone(self) -> None:
        with pytest.raises(ValueError):
            S02Config(entry_fraction=1.2)

    def test_both_bias_functions_are_the_documented_ones(self) -> None:
        from trading_os.domain.strategy.s01.bias import agreed_bias, daily_bias

        assert agreed_bias(BULLISH_HTF, BULLISH_HTF, 1) is Bias.BULLISH is daily_bias(BULLISH_HTF, BULLISH_HTF, 1)
