"""The commission an account pays: observed on its own deals, else documented, else an assumption that says so (ADR 0036)."""

from __future__ import annotations

from trading_os.domain.providers.commission import (
    CommissionDeal,
    CommissionSource,
    observed_commission,
    resolve_commission,
)
from trading_os.domain.providers.rules import ProviderProduct, rule_set_for


def deal(position: int, entry: str, volume: float, commission: float) -> CommissionDeal:
    return CommissionDeal(position_id=position, entry=entry, volume=volume, commission=commission)  # type: ignore[arg-type]


def round_trip(position: int, lots: float, per_side: float) -> list[CommissionDeal]:
    return [deal(position, "in", lots, -per_side * lots), deal(position, "out", lots, -per_side * lots)]


class TestObserved:
    def test_the_rate_is_what_was_charged_per_lot_over_a_round_trip(self) -> None:
        deals = round_trip(1, 1.0, 3.5) + round_trip(2, 0.5, 3.5)
        assert observed_commission(deals) == (7.0, 2)

    def test_a_broker_that_charges_nothing_is_an_observation_of_zero(self) -> None:
        assert observed_commission(round_trip(1, 0.1, 0.0)) == (0.0, 1)

    def test_a_position_still_open_or_half_closed_is_not_counted(self) -> None:
        open_only = [deal(1, "in", 1.0, -3.5)]
        partial = [deal(2, "in", 1.0, -3.5), deal(2, "out", 0.4, -1.4)]
        assert observed_commission(open_only + partial) is None
        assert observed_commission(open_only + partial + round_trip(3, 1.0, 3.5)) == (7.0, 1)

    def test_no_deals_is_no_observation_not_zero(self) -> None:
        assert observed_commission([]) is None

    def test_a_rebate_is_never_a_negative_cost(self) -> None:
        assert observed_commission([deal(1, "in", 1.0, 1.0), deal(1, "out", 1.0, 1.0)]) == (0.0, 1)


class TestResolution:
    exness = rule_set_for(ProviderProduct.EXNESS_STANDARD)
    ftmo = rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP)

    def test_observed_beats_everything(self) -> None:
        reading = resolve_commission(deals=round_trip(1, 1.0, 3.5), rule_set=self.exness, configured=5.0)
        assert (reading.source, reading.per_lot_round_trip, reading.round_trips) == (CommissionSource.OBSERVED, 7.0, 1)
        assert reading.documentary_mismatch  # the contract says none, the broker charged 7: shown, not hidden

    def test_an_observation_that_agrees_with_the_documentation_is_not_a_mismatch(self) -> None:
        reading = resolve_commission(deals=round_trip(1, 0.1, 0.0), rule_set=self.exness, configured=5.0)
        assert reading.source is CommissionSource.OBSERVED and reading.per_lot_round_trip == 0.0
        assert not reading.documentary_mismatch

    def test_without_deals_the_contract_documents_exness_standard_at_none_and_the_configured_five_is_not_used(
        self,
    ) -> None:
        reading = resolve_commission(deals=[], rule_set=self.exness, configured=5.0)
        assert (reading.source, reading.per_lot_round_trip) == (CommissionSource.DOCUMENTARY, 0.0)

    def test_an_unreadable_history_falls_back_to_the_documentation_not_to_zero_observed(self) -> None:
        reading = resolve_commission(deals=None, rule_set=self.exness, configured=5.0)
        assert reading.source is CommissionSource.DOCUMENTARY

    def test_a_contract_that_states_no_commission_leaves_the_configured_figure_as_an_assumption_that_says_so(
        self,
    ) -> None:
        reading = resolve_commission(deals=[], rule_set=self.ftmo, configured=5.0)
        assert (reading.source, reading.per_lot_round_trip) == (CommissionSource.ASSUMED, 5.0)
        assert "assumption" in reading.detail

    def test_an_unknown_product_is_an_assumption_too(self) -> None:
        assert resolve_commission(deals=None, rule_set=None, configured=2.0).source is CommissionSource.ASSUMED

    def test_the_first_observed_round_trip_replaces_the_assumption(self) -> None:
        reading = resolve_commission(deals=round_trip(1, 1.0, 2.0), rule_set=self.ftmo, configured=5.0)
        assert (reading.source, reading.per_lot_round_trip) == (CommissionSource.OBSERVED, 4.0)
        assert not reading.documentary_mismatch  # FTMO documents nothing to contradict
