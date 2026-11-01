"""Dynamic risk per trade (ADR 0019): the grid, the 200 $ trigger, the loss budgets left, and the strictest-wins rule."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trading_os.domain.risk.dynamic_risk import (
    OFFICIAL_GRID,
    DynamicRiskPolicy,
    GridTier,
    RemainingBudget,
    resolve_risk_allowance,
)

POLICY = DynamicRiskPolicy()
INITIAL = 10_000.0  # 1 % of it is 100 $: the percentages below read as dollars / 100


def allowance(performance_percent: float, **overrides: object):
    kwargs: dict[str, object] = {
        "initial_capital": INITIAL,
        "equity": INITIAL * (1 + performance_percent / 100),
        "per_trade_ceiling_percent": 1.5,
    }
    kwargs.update(overrides)
    return resolve_risk_allowance(POLICY, **kwargs)  # type: ignore[arg-type]


class TestTheGrid:
    """The mission's table, row by row (§6.2)."""

    @pytest.mark.parametrize(
        ("performance", "expected"),
        [
            (5.0, 1.5),
            (4.0, 1.5),  # « Risque à +4 % »
            (3.0, 1.5),
            (2.0, 1.5),
            (1.0, 1.5),  # « Risque à +1 % »
            (0.0, 1.0),  # « Risque au capital initial »
            (-1.0, 1.0),  # « Risque à -1 % »
            (-2.0, 0.1),  # « Risque à -2 % »
            (-3.0, 0.2),  # « Risque à -3 % »
            (-4.0, 0.3),  # « Risque à -4 % »
        ],
    )
    def test_each_row(self, performance: float, expected: float) -> None:
        result = allowance(performance)
        assert result.status == "allowed" and result.risk_percent == expected
        assert result.binding_cap == "grid"

    @pytest.mark.parametrize("performance", [-5.0, -5.01, -7.5, -40.0])
    def test_stop_at_minus_five_percent_and_below(self, performance: float) -> None:
        result = allowance(performance)
        assert result.status == "stopped" and result.risk_percent == 0.0
        assert result.reason == "performance_stop_reached"

    @pytest.mark.parametrize(
        ("performance", "expected"),
        [
            (0.4, 1.0),  # between the initial capital and +1 %
            (0.99, 1.0),
            (1.01, 1.5),
            (7.3, 1.5),  # above the top row: still the top row, never more
            (-0.01, 1.0),
            (-1.01, 1.0),  # the −1 % row holds until −2 % is reached
            (-1.99, 1.0),
            (-2.01, 0.1),  # −2 % reached, −3 % not yet
            (-2.99, 0.1),
            (-3.5, 0.2),
            (-4.99, 0.3),
        ],
    )
    def test_intermediate_values_take_the_level_reached_not_an_interpolation(
        self, performance: float, expected: float
    ) -> None:
        assert allowance(performance).risk_percent == expected

    def test_float_noise_does_not_drop_a_row(self) -> None:
        # 9800 / 10000 - 1 is -0.0200000000000018 in binary floating point: still the −2 % row, not the −1 % one.
        assert allowance(-2.0, equity=9800.0).risk_percent == 0.1
        assert allowance(-5.0, equity=9500.0).status == "stopped"

    def test_the_grid_never_exceeds_the_mission_ceiling(self) -> None:
        assert POLICY.ceiling_percent == 1.5 and POLICY.stop_level_percent == -5


class TestMissingReferences:
    def test_no_initial_capital_means_no_entry(self) -> None:
        result = allowance(0.0, initial_capital=None)
        assert result.status == "unavailable" and result.reason == "reference_capital_not_fixed"
        assert result.risk_percent == 0.0

    def test_no_equity_reading_means_no_entry(self) -> None:
        result = allowance(0.0, equity=0.0)
        assert result.status == "unavailable" and result.reason == "equity_unknown"


class TestAbsoluteLossTrigger:
    """§6.3: equity 200 $ under the initial capital caps the risk at 1 % — and never raises a lower one."""

    def test_caps_a_higher_risk(self) -> None:
        # A grid that would still allow 1.5 % under the initial capital: the trigger brings it down to 1 %.
        generous = DynamicRiskPolicy(
            grid=(
                GridTier(level_percent=1, risk_percent=1.5),
                GridTier(level_percent=0, risk_percent=1.5),
                GridTier(level_percent=-1, risk_percent=1.5),
                GridTier(level_percent=-2, risk_percent=None),
            )
        )
        # 100 000 $ so that 200 $ is only −0.2 %: the −0 row, which the generous grid still prices at 1.5 %.
        result = resolve_risk_allowance(
            generous, initial_capital=100_000.0, equity=100_000.0 - 200, per_trade_ceiling_percent=1.5
        )
        assert result.risk_percent == 1.0 and result.binding_cap == "absolute_loss_trigger"

    def test_199_dollars_does_not_trigger(self) -> None:
        generous = DynamicRiskPolicy(
            grid=(GridTier(level_percent=0, risk_percent=1.5), GridTier(level_percent=-1, risk_percent=None))
        )
        result = resolve_risk_allowance(
            generous, initial_capital=100_000.0, equity=100_000.0 - 199.99, per_trade_ceiling_percent=1.5
        )
        assert result.risk_percent == 1.5 and result.binding_cap == "grid"

    @pytest.mark.parametrize(("performance", "grid_risk"), [(-2.0, 0.1), (-3.0, 0.2), (-4.0, 0.3)])
    def test_never_raises_a_risk_the_grid_made_lower(self, performance: float, grid_risk: float) -> None:
        # §6.3's own example: the grid says 0.1 %, the 200 $ trigger must not bring it back to 1 %.
        result = allowance(performance)
        assert INITIAL - result_equity(performance) >= 200  # the trigger is active here
        assert result.risk_percent == grid_risk
        assert any(cap.code == "absolute_loss_trigger" for cap in result.caps)

    def test_recovery_climbs_the_grid_one_row_at_a_time(self) -> None:
        # Back from −4 % the risk follows the rows reached; it does not jump to the ceiling at once.
        path = [allowance(p).risk_percent for p in (-4.0, -3.0, -2.0, -1.0, 0.0, 1.0)]
        assert path == [0.3, 0.2, 0.1, 1.0, 1.0, 1.5]

    def test_with_the_official_grid_the_trigger_never_binds(self) -> None:
        # Documented in ADR 0019 §4: as written, the grid already caps at 1 % whenever the equity is under the
        # initial capital, so the trigger confirms it. The test pins that fact so a change is noticed.
        for performance in (-0.5, -1.0, -2.0, -3.0, -4.0, -4.9):
            assert allowance(performance).binding_cap == "grid"


def result_equity(performance_percent: float) -> float:
    return INITIAL * (1 + performance_percent / 100)


class TestStrictestRuleWins:
    def test_ceiling_of_the_profile_caps_every_trade(self) -> None:
        # The real account's earlier 0.1 % per trade (ADR 0015) stays effective as a ceiling.
        result = allowance(4.0, per_trade_ceiling_percent=0.1)
        assert result.risk_percent == 0.1 and result.binding_cap == "per_trade_ceiling"

    def test_remaining_daily_budget_caps_the_risk(self) -> None:
        budget = RemainingBudget(
            code="daily_budget", label="daily loss", limit_percent=5.0, used_percent=4.4, open_risk_percent=0.0
        )
        result = allowance(0.0, budgets=[budget])
        assert result.risk_percent == pytest.approx(0.6) and result.binding_cap == "daily_budget"

    def test_open_risk_counts_against_the_budget(self) -> None:
        budget = RemainingBudget(
            code="daily_budget", label="daily loss", limit_percent=5.0, used_percent=2.0, open_risk_percent=2.7
        )
        assert allowance(0.0, budgets=[budget]).risk_percent == pytest.approx(0.3)

    def test_weekly_budget_caps_the_risk(self) -> None:
        daily = RemainingBudget(code="daily_budget", label="daily loss", limit_percent=5.0, used_percent=0.0)
        weekly = RemainingBudget(code="weekly_budget", label="weekly loss", limit_percent=10.0, used_percent=9.5)
        result = allowance(0.0, budgets=[daily, weekly])
        assert result.risk_percent == pytest.approx(0.5) and result.binding_cap == "weekly_budget"

    def test_an_exhausted_budget_refuses_the_entry(self) -> None:
        spent = RemainingBudget(code="daily_budget", label="daily loss", limit_percent=5.0, used_percent=5.0)
        result = allowance(0.0, budgets=[spent])
        assert result.status == "stopped" and result.reason == "risk_budget_exhausted" and result.risk_percent == 0.0

    def test_a_budget_overdrawn_by_open_risk_refuses_too(self) -> None:
        over = RemainingBudget(
            code="daily_budget", label="daily loss", limit_percent=5.0, used_percent=4.0, open_risk_percent=3.0
        )
        assert allowance(0.0, budgets=[over]).reason == "risk_budget_exhausted"

    def test_the_allowance_is_floored_never_rounded_up(self) -> None:
        budget = RemainingBudget(
            code="daily_budget", label="daily loss", limit_percent=1.123456, used_percent=0.0, open_risk_percent=0.0
        )
        assert allowance(5.0, budgets=[budget]).risk_percent == 1.1234  # not 1.1235

    def test_a_tie_is_credited_to_the_grid(self) -> None:
        budget = RemainingBudget(code="daily_budget", label="daily loss", limit_percent=1.0, used_percent=0.0)
        assert allowance(0.0, budgets=[budget]).binding_cap == "grid"

    def test_every_cap_weighed_is_listed_for_the_audit_trail(self) -> None:
        budget = RemainingBudget(code="daily_budget", label="daily loss", limit_percent=5.0, used_percent=1.0)
        codes = [cap.code for cap in allowance(0.0, budgets=[budget]).caps]
        assert codes == ["grid", "per_trade_ceiling", "daily_budget"]


class TestPolicyValidation:
    def test_the_official_grid_is_valid_and_complete(self) -> None:
        assert [t.level_percent for t in OFFICIAL_GRID] == list(range(5, -6, -1))
        assert OFFICIAL_GRID[-1].risk_percent is None

    def test_a_gap_in_the_levels_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            DynamicRiskPolicy(
                grid=(
                    GridTier(level_percent=1, risk_percent=1.0),
                    GridTier(level_percent=-1, risk_percent=None),
                )
            )

    def test_a_grid_without_a_stop_row_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            DynamicRiskPolicy(
                grid=(GridTier(level_percent=0, risk_percent=1.0), GridTier(level_percent=-1, risk_percent=0.5))
            )

    def test_a_stop_row_in_the_middle_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            DynamicRiskPolicy(
                grid=(
                    GridTier(level_percent=0, risk_percent=None),
                    GridTier(level_percent=-1, risk_percent=0.5),
                    GridTier(level_percent=-2, risk_percent=None),
                )
            )

    def test_a_non_positive_risk_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            GridTier(level_percent=0, risk_percent=0.0)
