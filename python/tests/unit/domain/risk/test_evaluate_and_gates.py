"""Non-regression port of ``lib/risk/evaluate.test.ts`` and ``gates.test.ts`` + the gates the new engine adds."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.unit.domain.risk.fixtures import NOW, inputs
from trading_os.domain.market.calendar import UpcomingRelease
from trading_os.domain.risk.evaluate import evaluate_risk_state
from trading_os.domain.risk.gates import (
    connection_gate,
    correlation_gate,
    news_gate,
    open_risk_gate,
    position_limit_gate,
    spread_gate,
    symbol_gate,
)
from trading_os.domain.risk.policy import NewsPolicy, PositionLimits, RiskProfile
from trading_os.domain.risk.state import GateResult, RiskMode, RiskState, round_half_up


def gate(state: RiskState, gate_id: str) -> GateResult:
    return next(g for g in state.gates if g.gate_id == gate_id)


CPI = UpcomingRelease(release_id=10, label="CPI US", scheduled_at=datetime(2026, 1, 5, 14, 0, tzinfo=UTC))


class TestEvaluateRiskState:
    def test_normal_with_a_flat_account_inside_all_limits(self) -> None:
        state = evaluate_risk_state(inputs())
        assert state.mode is RiskMode.NORMAL
        assert state.lockout_reason is None
        assert all(not g.blocked for g in state.gates)

    def test_escalates_to_warning_past_60_percent_of_the_daily_loss_limit(self) -> None:
        # 5 % limit → warn at 3 %. Lose 35 on 1000 = 3.5 %.
        assert evaluate_risk_state(inputs(equity=965.0)).mode is RiskMode.WARNING

    def test_locks_when_the_daily_loss_limit_is_breached(self) -> None:
        state = evaluate_risk_state(inputs(equity=945.0))  # 5.5 % ≥ 5 %
        assert state.mode is RiskMode.LOCKED
        assert state.lockout_reason is not None and "Daily loss" in state.lockout_reason
        assert gate(state, "gate-daily-loss").blocked

    def test_closed_session_blocks_entries_without_locking(self) -> None:
        state = evaluate_risk_state(inputs(in_trading_window=False, window_label=None))
        assert state.mode is RiskMode.NORMAL
        assert gate(state, "gate-session").blocked

    def test_unknown_trade_counts_are_na_and_open_never_a_guessed_zero(self) -> None:
        state = evaluate_risk_state(inputs(trades_today=None, consecutive_losses=None))
        assert state.trades_today is None
        assert gate(state, "gate-max-trades").detail == "n/a (observe)"
        assert state.mode is RiskMode.NORMAL

    def test_locks_on_too_many_consecutive_losses(self) -> None:
        state = evaluate_risk_state(inputs(consecutive_losses=3))
        assert state.mode is RiskMode.LOCKED
        assert state.lockout_reason is not None and "Consecutive losses" in state.lockout_reason

    def test_locks_when_the_total_drawdown_limit_is_breached(self) -> None:
        state = evaluate_risk_state(inputs(equity=890.0, day_start_equity=890.0))  # 11 % under the reference
        assert state.mode is RiskMode.LOCKED
        assert gate(state, "gate-total-dd").blocked

    def test_locks_when_max_trades_is_reached(self) -> None:
        state = evaluate_risk_state(inputs(trades_today=6))
        assert state.mode is RiskMode.LOCKED and gate(state, "gate-max-trades").blocked

    # T03 — the most important behaviour of the news gate: absent data never reads as « all clear ».
    def test_news_gate_fails_closed_when_the_calendar_is_unknown(self) -> None:
        state = evaluate_risk_state(inputs(calendar=None))
        assert gate(state, "gate-news").blocked
        assert state.mode is RiskMode.NORMAL  # an entry gate, not an account lockout

    def test_news_blackout_around_a_whitelisted_release(self) -> None:
        state = evaluate_risk_state(inputs(now=datetime(2026, 1, 5, 13, 45, tzinfo=UTC), calendar=(CPI,)))
        assert gate(state, "gate-news").blocked

    def test_known_empty_calendar_stays_open(self) -> None:
        assert not gate(evaluate_risk_state(inputs(calendar=())), "gate-news").blocked

    # T09 — an order is refused while no agent is reachable, instead of failing later at send time.
    def test_no_agent_blocks_entries_but_does_not_lock(self) -> None:
        state = evaluate_risk_state(inputs(agent_connected=False))
        assert gate(state, "gate-connection").blocked
        assert state.mode is RiskMode.NORMAL and state.lockout_reason is None

    def test_agent_connected_opens_the_connection_gate(self) -> None:
        assert not gate(evaluate_risk_state(inputs(agent_connected=True)), "gate-connection").blocked

    def test_zero_reference_balance_does_not_divide_by_zero(self) -> None:
        assert evaluate_risk_state(inputs(initial_balance=0.0)).mode in set(RiskMode)

    def test_gate_ids_and_labels_keep_the_cockpit_contract(self) -> None:
        ids = [g.gate_id for g in evaluate_risk_state(inputs()).gates]
        for expected in (
            "gate-daily-loss",
            "gate-total-dd",
            "gate-open-risk",
            "gate-max-trades",
            "gate-consec-loss",
            "gate-spread",
            "gate-session",
            "gate-news",
            "gate-connection",
        ):
            assert expected in ids
        labels = {g.gate_id: g.label for g in evaluate_risk_state(inputs()).gates}
        assert labels["gate-daily-loss"] == "Daily loss guard" and labels["gate-connection"] == "Execution agent"

    def test_rounding_is_half_up_like_the_typescript_engine(self) -> None:
        assert round_half_up(3.45, 1) == 3.5  # Python's round() would say 3.5 or 3.4 depending on the float
        assert round_half_up(0.25, 1) == 0.3 and round_half_up(2.5, 0) == 3.0


class TestNewsGate:
    """Port of ``gates.test.ts``."""

    policy = NewsPolicy()
    now = datetime(2026, 9, 5, 13, 30, tzinfo=UTC)
    cpi = UpcomingRelease(release_id=10, label="CPI US", scheduled_at=datetime(2026, 9, 5, 14, 0, tzinfo=UTC))

    def test_blocks_when_releases_is_none(self) -> None:
        result = news_gate(None, self.now, self.policy)
        assert result.blocked and "no calendar data" in result.detail.lower()

    def test_an_empty_but_known_calendar_is_not_absent_data(self) -> None:
        assert not news_gate([], self.now, self.policy).blocked

    def test_blocks_inside_the_configured_window(self) -> None:
        assert news_gate([self.cpi], datetime(2026, 9, 5, 13, 45, tzinfo=UTC), self.policy).blocked

    def test_open_outside_the_window_and_reports_the_next_release(self) -> None:
        result = news_gate([self.cpi], datetime(2026, 9, 5, 10, 0, tzinfo=UTC), self.policy)
        assert not result.blocked and "CPI US" in result.detail

    def test_uses_the_policy_window_never_a_hardcoded_value(self) -> None:
        soon = self.cpi.model_copy(update={"scheduled_at": datetime(2026, 9, 5, 13, 45, tzinfo=UTC)})
        assert news_gate([soon], self.now, NewsPolicy(blackout_minutes=30)).blocked
        assert not news_gate([soon], self.now, NewsPolicy(blackout_minutes=5)).blocked


class TestNewGates:
    def test_a_position_without_a_stop_has_unbounded_risk_and_blocks(self) -> None:
        result = open_risk_gate(0.0, 2.0, unprotected=["987654"])
        assert result.blocked and "987654" in result.detail

    def test_an_unmeasured_position_blocks(self) -> None:
        assert open_risk_gate(0.0, 2.0, unknown_spec=["1"]).blocked

    def test_open_risk_over_the_limit_blocks_equal_does_not(self) -> None:
        assert open_risk_gate(2.01, 2.0).blocked
        assert not open_risk_gate(2.0, 2.0).blocked

    def test_correlated_exposure_gate(self) -> None:
        assert correlation_gate(2.0, 1.5, ("USD", "short")).blocked
        assert not correlation_gate(1.5, 1.5, None).blocked

    def test_position_limit_gate(self) -> None:
        limits = PositionLimits(max_open_positions=2)
        assert not position_limit_gate(1, limits).blocked and position_limit_gate(2, limits).blocked

    def test_spread_gate_has_no_fixed_cap_by_default(self) -> None:
        assert not spread_gate(0.00080, None).blocked  # ADR 0015: the cost gate decides, not a fixed ceiling

    def test_spread_gate_user_cap_unknown_and_invalid(self) -> None:
        assert spread_gate(0.0003, 0.0002).blocked
        assert not spread_gate(0.0001, 0.0002).blocked
        assert not spread_gate(None, None).blocked  # observation: unknown is n/a
        assert spread_gate(None, None, require_tick=True).blocked  # an order in view needs a live tick
        assert spread_gate(0.0, None).blocked  # a zero/negative spread is a feed fault, not a bargain

    def test_symbol_gate(self) -> None:
        assert not symbol_gate("EURUSDm", None).blocked
        assert not symbol_gate("EURUSDm", frozenset({"EURUSDm"})).blocked
        assert symbol_gate("EURUSDm", frozenset({"XAUUSDm"})).blocked

    def test_connection_gate_is_never_nullable(self) -> None:
        assert connection_gate(False).blocked and not connection_gate(True).blocked

    def test_profile_defaults_do_not_claim_to_be_configured(self) -> None:
        assert RiskProfile().configured is False  # autonomy refuses to start on defaults (ADR 0015)
        assert NOW.tzinfo is not None
        with pytest.raises(ValueError):
            RiskProfile(max_trades_per_day=0)
