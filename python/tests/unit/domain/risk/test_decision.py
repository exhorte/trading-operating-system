"""« CAN_I_TRADE? » and the ``RiskDecision`` on an intent — the single control point before execution (ADR 0007)."""

from __future__ import annotations

from datetime import timedelta

from tests.unit.domain.risk.fixtures import ACCOUNT, EURUSD, GBPUSD, NOW, SPECS, inputs, position
from trading_os.domain.primitives import Side
from trading_os.domain.risk.decision import (
    HealthFlags,
    IntentReview,
    TradingContext,
    can_i_trade,
    decide,
)
from trading_os.domain.risk.lockout import CONSECUTIVE_LOSS_REASON, KILL_SWITCH_REASON, ActiveLockout
from trading_os.domain.risk.policy import PositionLimits, RiskProfile
from trading_os.domain.strategy.intent import TradeIntent

SYMBOL = "EURUSDm"


def context(**risk_overrides: object) -> TradingContext:
    health = risk_overrides.pop("health", HealthFlags())
    lockout = risk_overrides.pop("lockout", None)
    allowed = risk_overrides.pop("allowed", None)
    positions = risk_overrides.pop("positions", ())
    return TradingContext(
        risk=inputs(**risk_overrides),
        health=health,
        active_lockout=lockout,
        allowed_symbols=allowed,
        positions=positions,
        specs=SPECS,
    )


def intent(**overrides: object) -> TradeIntent:
    base: dict[str, object] = {
        "intent_id": "intent-1",
        "account_id": ACCOUNT,
        "strategy_id": "S01",
        "strategy_version": "1",
        "symbol": SYMBOL,
        "side": Side.BUY,
        "entry_price": 1.1000,
        "stop_loss": 1.0990,
        "take_profit": 1.1030,
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=1),
    }
    base.update(overrides)
    return TradeIntent(**base)


def review(**overrides: object) -> IntentReview:
    base: dict[str, object] = {"spec": EURUSD, "spread": 0.00008}
    base.update(overrides)
    return IntentReview(**base)


class TestCanITrade:
    def test_allowed_on_a_clean_context(self) -> None:
        result = can_i_trade(context(), symbol=SYMBOL)
        assert result.decision == "ALLOWED" and result.reasons == []
        assert all(c.ok for c in result.checks)

    def test_explains_every_reason_in_a_stable_order(self) -> None:
        # The mission's own example: daily budget gone + news restriction + correlated exposure. At -5.5 % of the
        # initial capital the grid's stop (ADR 0019) is reached too; the allowance repeats that code, which shows once.
        result = can_i_trade(
            context(equity=945.0, calendar=None, correlated_exposure_percent=2.0, correlated_key=("USD", "short")),
            symbol=SYMBOL,
        )
        assert result.decision == "DENIED"
        assert result.reasons == [
            "daily_risk_budget_exceeded",
            "performance_stop_reached",
            "correlated_exposure_too_high",
            "news_restriction",
        ]

    def test_all_seventeen_checks_of_the_mission_are_present(self) -> None:
        ids = {c.check_id for c in can_i_trade(context(), symbol=SYMBOL).checks}
        assert {
            "account_healthy",
            "broker_connected",
            "mt5_healthy",
            "account_rules",
            "daily_loss",
            "max_drawdown",
            "open_risk",
            "correlation",
            "news",
            "spread",
            "session",
            "symbol",
            "position_limit",
            "max_trades",
            "kill_switch",
            "autonomy",
            "execution_agent",
        } <= ids

    def test_each_health_flag_maps_to_its_reason(self) -> None:
        cases = {
            "account_healthy": "account_unhealthy",
            "broker_connected": "broker_disconnected",
            "mt5_healthy": "mt5_unhealthy",
            "account_trading_enabled": "account_trading_disabled",
            "autonomy_permits_entries": "autonomy_not_permitting",
            "execution_agent_healthy": "execution_agent_unhealthy",
        }
        for flag, reason in cases.items():
            result = can_i_trade(context(health=HealthFlags(**{flag: False})), symbol=SYMBOL)
            assert result.reasons == [reason], flag

    def test_symbol_not_allowed(self) -> None:
        result = can_i_trade(context(allowed=frozenset({"XAUUSDm"})), symbol=SYMBOL)
        assert result.reasons == ["symbol_not_allowed"]
        assert can_i_trade(context(allowed=frozenset({"XAUUSDm"}))).decision == "ALLOWED"  # no symbol in view

    def test_position_limit_and_max_trades(self) -> None:
        limits = RiskProfile(positions=PositionLimits(max_open_positions=2))
        assert can_i_trade(context(profile=limits, open_positions=2), symbol=SYMBOL).reasons == [
            "position_limit_reached"
        ]
        assert can_i_trade(context(trades_today=15), symbol=SYMBOL).reasons == ["max_trades_reached"]
        assert can_i_trade(context(trades_today=14), symbol=SYMBOL).reasons == []
        assert can_i_trade(context(consecutive_losses=3), symbol=SYMBOL).reasons == ["consecutive_losses_limit"]

    def test_kill_switch_and_other_lockouts(self) -> None:
        kill = ActiveLockout(lockout_id="k", reason=KILL_SWITCH_REASON, since=NOW)
        assert can_i_trade(context(lockout=kill), symbol=SYMBOL).reasons == ["kill_switch_active"]
        assert can_i_trade(context(health=HealthFlags(kill_switch_active=True)), symbol=SYMBOL).reasons == [
            "kill_switch_active"
        ]
        other = ActiveLockout(lockout_id="d", reason="Daily loss guard", since=NOW)
        assert can_i_trade(context(lockout=other), symbol=SYMBOL).reasons == ["account_locked"]

    def test_an_expired_pause_no_longer_locks(self) -> None:
        expired = ActiveLockout(
            lockout_id="p",
            reason=CONSECUTIVE_LOSS_REASON,
            since=NOW - timedelta(hours=1),
            until=NOW - timedelta(minutes=1),
        )
        assert can_i_trade(context(lockout=expired), symbol=SYMBOL).decision == "ALLOWED"

    def test_an_order_in_view_needs_a_live_tick_but_a_general_question_does_not(self) -> None:
        assert can_i_trade(context(spread=None), symbol=SYMBOL).reasons == ["no_live_tick"]
        assert can_i_trade(context(spread=None)).decision == "ALLOWED"


class TestDecide:
    def test_approves_and_sizes_from_the_broker_specification(self) -> None:
        decision = decide(context(), intent(), review())
        # 1 % of 1000 = 10 USD ; (0.0010 + 0.00008) ÷ 0.00001 = 108 USD/lot → 0.0926 → 0.09 lot
        assert decision.approved and decision.reasons == []
        assert decision.approved_volume == 0.09
        assert decision.sizing is not None and decision.sizing.risk_at_stop <= 10.0
        assert decision.account_id == ACCOUNT and decision.intent_id == "intent-1"
        assert decision.expires_at == NOW + timedelta(seconds=60)
        assert len(decision.gates) >= 9

    def test_a_refusal_always_returns_a_decision_with_its_reasons(self) -> None:
        decision = decide(context(equity=945.0), intent(), review())
        assert not decision.approved and decision.approved_volume is None and decision.sizing is None
        assert "daily_risk_budget_exceeded" in decision.reasons

    def test_stop_on_the_wrong_side(self) -> None:
        decision = decide(context(), intent(stop_loss=1.1010), review())
        assert not decision.approved and "stop_wrong_side" in decision.reasons and decision.approved_volume is None

    def test_target_on_the_wrong_side(self) -> None:
        assert "target_wrong_side" in decide(context(), intent(take_profit=1.0950), review()).reasons

    def test_cost_gate(self) -> None:
        # spread 0.00030 on a 0.0010 stop → c = 0.30 > 0.25
        decision = decide(context(spread=0.00030), intent(), review(spread=0.00030))
        assert "cost_too_high" in decision.reasons and not decision.approved

    def test_cost_gate_includes_the_commission(self) -> None:
        # 0.00008 spread + 7 USD/lot commission (0.00007) = 0.00015 ÷ 0.0006 stop = 0.25: exactly the threshold, allowed
        ok = decide(context(), intent(stop_loss=1.0994), review(commission_per_lot_round_trip=7.0))
        assert "cost_too_high" not in ok.reasons
        too_much = decide(context(), intent(stop_loss=1.0994), review(commission_per_lot_round_trip=9.0))
        assert "cost_too_high" in too_much.reasons

    def test_minimum_lot_over_the_budget_is_a_refusal(self) -> None:
        decision = decide(
            context(
                balance=100.0, equity=100.0, day_start_equity=100.0, week_start_equity=100.0, initial_balance=100.0
            ),
            intent(),
            review(),
        )
        assert "min_volume_exceeds_risk" in decision.reasons and not decision.approved

    def test_open_risk_after_the_trade_is_checked(self) -> None:
        decision = decide(context(open_risk_percent=1.9), intent(), review())
        assert "open_risk_too_high" in decision.reasons and not decision.approved

    def test_correlated_exposure_after_the_trade_is_checked(self) -> None:
        # 10 000 USD account; a long GBPUSD (80 USD = 0.8 %) is open; a long EURUSD adds ~1 % on the same short-USD leg.
        gbp = position("g1", "GBPUSDm", Side.BUY, 0.8, 1.2500, 1.2490)
        ctx = context(
            balance=10_000.0,
            equity=10_000.0,
            day_start_equity=10_000.0,
            initial_balance=10_000.0,
            open_risk_percent=0.8,
            open_positions=1,
            positions=(gbp,),
        )
        assert GBPUSD.name in ctx.specs
        decision = decide(ctx, intent(), review())
        assert "correlated_exposure_too_high" in decision.reasons and not decision.approved

    def test_a_long_and_a_short_on_the_same_pair_family_do_not_correlate(self) -> None:
        gbp = position("g1", "GBPUSDm", Side.SELL, 0.8, 1.2490, 1.2500)
        ctx = context(
            balance=10_000.0,
            equity=10_000.0,
            day_start_equity=10_000.0,
            initial_balance=10_000.0,
            open_risk_percent=0.8,
            open_positions=1,
            positions=(gbp,),
        )
        assert decide(ctx, intent(), review()).approved

    def test_unknown_symbol_specification(self) -> None:
        decision = decide(context(), intent(), review(spec=None))
        assert "symbol_spec_missing" in decision.reasons and not decision.approved

    def test_per_order_volume_cap_applies(self) -> None:
        big = context(balance=100_000.0, equity=100_000.0, day_start_equity=100_000.0, initial_balance=100_000.0)
        decision = decide(big, intent(), review(max_volume_per_order=2.0))
        assert decision.approved and decision.approved_volume == 2.0

    def test_decision_ids_are_unique(self) -> None:
        a, b = decide(context(), intent(), review()), decide(context(), intent(), review())
        assert a.decision_id != b.decision_id
