"""N8 « Drawdown Flatlining » as a cap on the next trade's risk (ADR 0031): reduce-only, whole 0.1 % units, inert until its smallest unit is
written, and one more entry in the Risk Engine's minimum — never a way round a limit."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trading_os.app.config import Settings
from trading_os.domain.risk.dynamic_risk import (
    AppliedCap,
    DynamicRiskPolicy,
    RemainingBudget,
    resolve_risk_allowance,
)
from trading_os.domain.risk.n8 import (
    N8Policy,
    evaluate_n8,
    percent_to_units,
    units_to_percent,
)

W, L, Z = 1.0, -1.0, 0.0  # a win, a loss, a trade that made nothing


def policy(minimum_percent: float | None = 0.1, **kwargs: object) -> N8Policy:
    return N8Policy.from_percent(enabled=True, minimum_percent=minimum_percent, **kwargs)  # type: ignore[arg-type]


def cap(
    pnl: list[float], p: N8Policy | None = None, *, equity: float = 10_100, start: float = 10_000, known: bool = True
):  # type: ignore[no-untyped-def]
    return evaluate_n8(p or policy(), pnl_oldest_first=pnl, history_known=known, equity=equity, starting_capital=start)


class TestTheGranularityIsOneTenthOfAPercent:
    def test_values_are_whole_units_and_exact(self) -> None:
        assert [units_to_percent(u) for u in (0, 1, 3, 10, 15)] == [0.0, 0.1, 0.3, 1.0, 1.5]
        assert units_to_percent(3) == 0.3  # not 0.30000000000000004
        assert [percent_to_units(p) for p in (0, 0.1, 0.3, 0.7, 1.5)] == [0, 1, 3, 7, 15]

    @pytest.mark.parametrize("value", [0.05, 0.15, 0.123, -0.1])
    def test_a_value_between_two_units_is_refused_not_rounded(self, value: float) -> None:
        with pytest.raises(ValueError):
            percent_to_units(value)
        with pytest.raises(ValueError):
            N8Policy.from_percent(enabled=True, minimum_percent=value)

    def test_the_setting_is_checked_when_the_core_starts(self) -> None:
        assert Settings(_env_file=None, risk_n8_minimum_percent=0.3).risk_n8_minimum_percent == 0.3
        with pytest.raises(ValidationError):
            Settings(_env_file=None, risk_n8_minimum_percent=0.25)
        with pytest.raises(ValidationError):
            Settings(_env_file=None, risk_n8_minimum_percent=-0.1)

    def test_the_smallest_unit_is_not_a_required_minimum_it_can_be_zero(self) -> None:
        zero = cap([L], policy(0.0))
        assert zero.state == "restricted" and zero.cap_percent == 0.0


class TestNothingIsInventedAboutWhatTheNotesLeaveOpen:
    def test_off_by_default_and_inert_until_the_smallest_unit_is_written(self) -> None:
        assert cap([L], N8Policy()).state == "off"
        unwritten = cap([L], policy(None))
        assert unwritten.state == "unconfigured" and unwritten.cap_percent is None
        assert "not written" in unwritten.detail

    def test_the_settings_default_is_off_with_no_unit(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.risk_n8_enabled is False and settings.risk_n8_minimum_percent is None
        assert settings.risk_n8_wins_before_minimum == 5  # the notes' own number (§j.4)

    def test_there_is_no_step_up_and_no_soft_start_to_switch_on(self) -> None:
        fields = set(N8Policy.model_fields)
        assert fields == {
            "enabled",
            "minimum_units",
            "reduce_after_loss",
            "wins_before_minimum",
            "reduce_below_starting_equity",
        }


class TestTheTriggersTheNotesGive:
    def test_one_loss_means_the_smallest_unit_until_a_trade_wins(self) -> None:
        assert cap([W, W, L]).triggers == ("after_loss",)
        assert cap([W, L, L]).state == "restricted"
        assert cap([L, W]).state == "free"  # a validated win releases it: the grid decides again

    def test_a_trade_that_made_nothing_changes_nothing(self) -> None:
        assert cap([L, Z]).state == "restricted"  # still no winning trade
        assert cap([W, Z]).state == "free"
        assert cap([Z, Z]).state == "free"

    def test_no_history_is_no_trigger(self) -> None:
        assert cap([]).state == "free"

    def test_five_wins_in_a_row_put_the_sixth_trade_at_the_minimum_then_the_counter_restarts(self) -> None:
        assert cap([W] * 4).state == "free"
        five = cap([W] * 5)
        assert five.state == "restricted" and five.triggers == ("win_set_cycle",)
        assert cap([W] * 6).state == "free"  # the trade at the minimum won: a new cycle starts at zero
        assert cap([W] * 6 + [W] * 4).state == "free"
        assert cap([W] * 6 + [W] * 5).state == "restricted"  # five more
        assert cap([W] * 5 + [L]).triggers == (
            "after_loss",
        )  # the sixth lost: the loss rule, the counter is zero again

    def test_a_loss_inside_the_run_restarts_the_count(self) -> None:
        assert cap([W, W, W, L, W, W, W, W]).state == "free"  # 4 wins since the loss
        assert cap([W, W, W, L, W, W, W, W, W]).state == "restricted"

    def test_equity_under_the_starting_capital_means_the_minimum(self) -> None:
        under = cap([W], equity=9_950)
        assert under.state == "restricted" and under.triggers == ("below_starting_equity",)
        assert cap([W], equity=10_000).state == "free"  # at the start is not under it
        assert (
            cap([W], equity=9_950, start=None).state == "free"
        )  # no starting capital recorded: nothing to compare (and the grid refuses anyway)

    def test_each_trigger_can_be_switched_off_on_its_own(self) -> None:
        assert cap([L], policy(reduce_after_loss=False)).state == "free"
        assert cap([W] * 5, policy(wins_before_minimum=0)).state == "free"
        assert cap([W], policy(reduce_below_starting_equity=False), equity=9_000).state == "free"

    def test_several_triggers_are_all_named_and_the_cap_is_still_one_value(self) -> None:
        both = cap([L], equity=9_000)
        assert both.triggers == ("after_loss", "below_starting_equity") and both.cap_percent == 0.1
        assert "the last trade lost" in both.detail and "under the starting capital" in both.detail

    def test_a_history_that_cannot_be_read_applies_the_minimum_never_an_assumption_of_more_risk(self) -> None:
        unknown = cap([W, W], known=False)
        assert unknown.state == "restricted" and "history_unknown" in unknown.triggers


class TestItOnlyEverLowersTheRisk:
    """ADR 0031: N8 is one more cap in the minimum. The grid, the ceiling and the loss budgets keep deciding."""

    @staticmethod
    def allowance(
        extra: tuple[AppliedCap, ...] = (), *, equity: float = 10_000, budgets: tuple[RemainingBudget, ...] = ()
    ):  # type: ignore[no-untyped-def]
        return resolve_risk_allowance(
            DynamicRiskPolicy(),
            initial_capital=10_000.0,
            equity=equity,
            per_trade_ceiling_percent=1.5,
            budgets=budgets,
            extra_caps=extra,
        )

    @staticmethod
    def n8_cap(percent: float) -> AppliedCap:
        return AppliedCap(code="n8_flatlining", limit_percent=percent, detail="N8 test")

    def test_without_n8_nothing_changes(self) -> None:
        plain = self.allowance()
        assert (plain.status, plain.risk_percent, plain.binding_cap) == ("allowed", 1.0, "grid")

    def test_n8_can_lower_the_risk_in_tenths_of_a_percent(self) -> None:
        lowered = self.allowance((self.n8_cap(0.3),))
        assert (lowered.risk_percent, lowered.binding_cap) == (0.3, "n8_flatlining")
        assert any(c.code == "n8_flatlining" for c in lowered.caps)  # the decision records it

    def test_n8_never_raises_what_the_grid_already_made_lower(self) -> None:
        low_grid = self.allowance((self.n8_cap(1.5),), equity=9_800)  # −2 % row → 0.1 %
        assert (low_grid.risk_percent, low_grid.binding_cap) == (0.1, "grid")

    def test_a_larger_n8_cap_changes_nothing(self) -> None:
        assert self.allowance((self.n8_cap(5.0),)).risk_percent == self.allowance().risk_percent == 1.0

    def test_n8_cannot_go_round_a_loss_budget(self) -> None:
        budget = RemainingBudget(code="daily_budget", label="daily loss", limit_percent=5.0, used_percent=4.8)
        result = self.allowance((self.n8_cap(0.5),), budgets=(budget,))
        assert (result.risk_percent, result.binding_cap) == (
            0.2,
            "daily_budget",
        )  # 0.2 % left of the day, N8's 0.5 % is not a licence

    def test_a_zero_cap_blocks_the_next_trade(self) -> None:
        blocked = self.allowance((self.n8_cap(0.0),))
        assert blocked.status == "stopped" and blocked.risk_percent == 0.0
        assert blocked.reason == "risk_budget_exhausted" and "n8_flatlining" in blocked.detail

    def test_on_a_tie_the_grid_keeps_the_blame(self) -> None:
        assert self.allowance((self.n8_cap(1.0),)).binding_cap == "grid"
