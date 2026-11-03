"""The official limits of ADR 0019, end to end through the evaluator and the decision: 15 trades, 5 positions, the
weekly and daily loss limits, the −5 % performance stop, the dynamic grid driving the lot, and the same rules for
Exness and FTMO."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.domain.risk.fixtures import ACCOUNT, EURUSD, NOW, SPECS, XAUUSD, inputs
from trading_os.domain.accounts.models import (
    AccountRules,
    AccountType,
    ExecutionProfile,
    FtmoChallenge,
    Provider,
    TradingRules,
)
from trading_os.domain.accounts.profiles import (
    ProfileParams,
    apply_provider_ceilings,
    default_rules,
    provider_ceilings,
)
from trading_os.domain.primitives import Side
from trading_os.domain.risk.decision import HealthFlags, IntentReview, TradingContext, can_i_trade, decide
from trading_os.domain.risk.evaluate import evaluate_risk_state
from trading_os.domain.risk.policy import DrawdownPolicy, PositionLimits, RiskProfile
from trading_os.domain.risk.state import RiskMode
from trading_os.domain.risk.trading_day import resolve_week_start_utc
from trading_os.domain.strategy.intent import TradeIntent

INITIAL = 10_000.0


def account(performance: float, **overrides: object) -> dict[str, object]:
    """An account `performance` % away from its initial capital, with a flat day and a flat week."""
    equity = round(INITIAL * (1 + performance / 100), 2)
    base: dict[str, object] = {
        "initial_balance": INITIAL,
        "balance": equity,
        "equity": equity,
        "day_start_equity": equity,
        "week_start_equity": equity,
    }
    base.update(overrides)
    return base


def context(**risk_overrides: object) -> TradingContext:
    return TradingContext(risk=inputs(**risk_overrides), health=HealthFlags(), specs=SPECS)


def eur_intent() -> TradeIntent:
    return TradeIntent(
        intent_id="i-eur",
        account_id=ACCOUNT,
        strategy_id="S01",
        strategy_version="1",
        symbol="EURUSDm",
        side=Side.BUY,
        entry_price=1.1000,
        stop_loss=1.0990,
        take_profit=1.1030,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )


def gold_intent() -> TradeIntent:
    return eur_intent().model_copy(
        update={"intent_id": "i-xau", "symbol": "XAUUSDm", "entry_price": 2000.0, "stop_loss": 1998.0,
                "take_profit": 2006.0}
    )  # fmt: skip


def review_for(symbol: str) -> IntentReview:
    spec = SPECS[symbol]
    spread = 0.00008 if symbol == "EURUSDm" else 0.10
    return IntentReview(spec=spec, spread=spread)


class TestGeneralLimits:
    def test_the_official_defaults(self) -> None:
        profile = RiskProfile()
        assert profile.max_trades_per_day == 15
        assert profile.positions.max_open_positions == 5
        assert profile.drawdown.daily_loss_limit_percent == 5.0
        assert profile.drawdown.weekly_loss_limit_percent == 10.0
        assert profile.max_risk_per_trade_percent == 1.5

    def test_fifteen_trades_a_day_then_no_more(self) -> None:
        assert can_i_trade(context(trades_today=14), symbol="EURUSDm").reasons == []
        reached = can_i_trade(context(trades_today=15), symbol="EURUSDm")
        assert reached.decision == "DENIED" and reached.reasons == ["max_trades_reached"]

    def test_five_simultaneous_positions_then_no_more(self) -> None:
        assert can_i_trade(context(open_positions=4), symbol="EURUSDm").reasons == []
        reached = can_i_trade(context(open_positions=5), symbol="EURUSDm")
        assert reached.reasons == ["position_limit_reached"]

    def test_the_position_limit_counts_the_whole_account_not_each_symbol(self) -> None:
        # Two symbols are the whole universe: 2 on one + 3 on the other is 5, and the sixth is refused on either.
        for symbol in ("EURUSDm", "XAUUSDm"):
            assert "position_limit_reached" in can_i_trade(context(open_positions=5), symbol=symbol).reasons


class TestWeeklyLoss:
    PROFILE = RiskProfile(drawdown=DrawdownPolicy(weekly_loss_limit_percent=2.0, reference_balance=INITIAL))

    def test_reaching_the_weekly_limit_locks_and_names_the_reason(self) -> None:
        # Day flat, week started 2.5 % higher: only the weekly limit is breached (−2.5 % of 10 000 vs the initial).
        state = evaluate_risk_state(inputs(**account(-2.5, week_start_equity=INITIAL), profile=self.PROFILE))
        assert state.mode is RiskMode.LOCKED and state.weekly_loss_used_percent == 2.5
        assert state.lockout_reason == "Weekly loss guard"
        assert next(g for g in state.gates if g.gate_id == "gate-weekly-loss").blocked
        denied = can_i_trade(context(**account(-2.5, week_start_equity=INITIAL), profile=self.PROFILE), "EURUSDm")
        assert "weekly_loss_limit_reached" in denied.reasons

    def test_below_the_limit_the_week_stays_open(self) -> None:
        state = evaluate_risk_state(inputs(**account(-1.5, week_start_equity=INITIAL), profile=self.PROFILE))
        assert not next(g for g in state.gates if g.gate_id == "gate-weekly-loss").blocked

    def test_floating_loss_counts(self) -> None:
        # Balance untouched, equity down: the open positions' floating loss is part of the week's loss.
        floating = inputs(**account(-2.5, week_start_equity=INITIAL, balance=INITIAL), profile=self.PROFILE)
        assert next(g for g in evaluate_risk_state(floating).gates if g.gate_id == "gate-weekly-loss").blocked

    def test_a_new_week_reference_reopens_the_gate_but_the_global_loss_stays(self) -> None:
        # Monday: the week restarts from the current equity. The weekly gate opens; the performance is still −2.5 %,
        # so the grid still prices the trade at 0.1 % — a new week never erases a loss against the initial capital.
        monday = evaluate_risk_state(inputs(**account(-2.5), profile=self.PROFILE))
        assert not next(g for g in monday.gates if g.gate_id == "gate-weekly-loss").blocked
        assert monday.allowance.grid_percent == 0.1

    def test_the_default_limit_is_ten_percent(self) -> None:
        blocked = evaluate_risk_state(inputs(**account(-4.9, week_start_equity=INITIAL * 1.051)))
        # −4.9 % vs initial, week started +5.1 %: a 10 % weekly loss, while the day and the total are fine.
        assert next(g for g in blocked.gates if g.gate_id == "gate-weekly-loss").blocked
        assert not next(g for g in blocked.gates if g.gate_id == "gate-daily-loss").blocked


class TestDailyLossAndPerformanceStop:
    def test_five_percent_lost_today_blocks_everything(self) -> None:
        state = evaluate_risk_state(inputs(**account(0.0, equity=9500.0, day_start_equity=INITIAL)))
        assert state.mode is RiskMode.LOCKED and next(g for g in state.gates if g.gate_id == "gate-daily-loss").blocked

    def test_minus_five_percent_of_the_initial_capital_is_a_stop_whatever_the_day(self) -> None:
        # Flat day, flat week: only the grid's last row is reached — and it holds on every following day.
        state = evaluate_risk_state(inputs(**account(-5.0)))
        stop = next(g for g in state.gates if g.gate_id == "gate-performance-stop")
        assert stop.blocked and state.mode is RiskMode.LOCKED
        assert state.lockout_reason == "Performance stop"
        assert state.allowance.status == "stopped"

    def test_just_above_minus_five_percent_is_still_open(self) -> None:
        state = evaluate_risk_state(inputs(**account(-4.99)))
        assert not next(g for g in state.gates if g.gate_id == "gate-performance-stop").blocked
        assert state.allowance.risk_percent == 0.3

    def test_a_denied_decision_explains_the_stop_and_sizes_nothing(self) -> None:
        decision = decide(context(**account(-5.0)), eur_intent(), review_for("EURUSDm"))
        assert not decision.approved and "performance_stop_reached" in decision.reasons
        assert decision.sizing is None and decision.approved_volume is None
        assert decision.allowance is not None and decision.allowance.status == "stopped"

    def test_the_gate_stays_closed_without_an_initial_capital_but_entries_are_refused(self) -> None:
        state = evaluate_risk_state(inputs(**account(-8.0), reference_fixed=False))
        assert state.performance_percent is None
        decision = decide(context(**account(0.0), reference_fixed=False), eur_intent(), review_for("EURUSDm"))
        assert not decision.approved and "reference_capital_not_fixed" in decision.reasons


class TestTheGridDrivesTheLot:
    @pytest.mark.parametrize(
        ("performance", "risk_percent"),
        [(5.0, 1.5), (4.0, 1.5), (1.0, 1.5), (0.0, 1.0), (-1.0, 1.0), (-2.0, 0.1), (-3.0, 0.2), (-4.0, 0.3)],
    )
    @pytest.mark.parametrize("symbol", ["EURUSDm", "XAUUSDm"])
    def test_the_lot_never_exceeds_the_allowed_risk(self, performance: float, risk_percent: float, symbol: str) -> None:
        intent = eur_intent() if symbol == "EURUSDm" else gold_intent()
        # Equity and balance equal: the sizing base is that figure.
        ctx = context(**account(performance, open_risk_percent=0.0), profile=RiskProfile())
        decision = decide(ctx, intent, review_for(symbol))
        assert decision.approved, decision.reasons
        assert decision.allowance is not None and decision.allowance.risk_percent == risk_percent
        base = ctx.risk.equity
        sizing = decision.sizing
        assert sizing is not None
        assert sizing.risk_budget == pytest.approx(base * risk_percent / 100, abs=0.01)
        assert sizing.risk_at_stop <= base * risk_percent / 100 + 1e-6  # floored, never above
        assert sizing.effective_risk_percent <= risk_percent + 1e-9

    def test_a_worked_example_at_plus_four_percent(self) -> None:
        # 10 400 $ of equity, 1.5 % = 156 $. EURUSD, 10-pip stop + 0.8-pip spread: 108 $ per lot → 1.44 lots.
        decision = decide(context(**account(4.0)), eur_intent(), review_for("EURUSDm"))
        assert decision.approved and decision.approved_volume == 1.44
        assert decision.sizing is not None and decision.sizing.risk_at_stop == pytest.approx(155.52)
        assert decision.sizing.effective_risk_percent == pytest.approx(1.4954, abs=1e-4)

    def test_the_risk_estimate_is_on_the_decision_before_anything_is_sent(self) -> None:
        decision = decide(context(**account(0.0)), eur_intent(), review_for("EURUSDm"))
        assert decision.sizing is not None and decision.sizing.risk_at_stop > 0
        assert decision.allowance is not None and decision.allowance.binding_cap == "grid"
        assert [cap.code for cap in decision.allowance.caps][:2] == ["grid", "per_trade_ceiling"]

    def test_the_lot_is_sized_on_the_lower_of_balance_and_equity(self) -> None:
        # Equity above the balance (floating profit): sized on the balance. Equity below: sized on the equity.
        above = decide(context(**account(0.0, balance=9_000.0, equity=10_000.0)), eur_intent(), review_for("EURUSDm"))
        assert above.sizing is not None and above.sizing.risk_budget == pytest.approx(9_000.0 * 0.01)
        below = decide(context(**account(0.0, balance=10_000.0, equity=9_900.0)), eur_intent(), review_for("EURUSDm"))
        assert below.sizing is not None and below.sizing.risk_budget == pytest.approx(9_900.0 * 0.01)

    def test_a_minimum_lot_over_the_allowance_is_refused_not_rounded_up(self) -> None:
        # 0.1 % of 10 000 = 10 $ ; gold, 2.00 stop = 200 $ per lot → even 0.01 lot (2 $ + spread) fits, so tighten:
        wide = gold_intent().model_copy(update={"stop_loss": 1900.0})  # 100.0 away: 10 000 $ per lot, 100 $ at 0.01
        decision = decide(context(**account(-2.0)), wide, review_for("XAUUSDm"))
        assert not decision.approved and "min_volume_exceeds_risk" in decision.reasons

    def test_the_remaining_daily_budget_can_be_stricter_than_the_grid(self) -> None:
        # Four positions already carry 4.7 % of open risk: only 0.3 % of the day's 5 % is left, the grid says 1 %.
        profile = RiskProfile(max_open_risk_percent=10.0, max_correlated_risk_percent=10.0)
        decision = decide(
            context(**account(0.0, open_risk_percent=4.7), profile=profile), eur_intent(), review_for("EURUSDm")
        )
        assert decision.allowance is not None
        assert decision.allowance.binding_cap == "daily_budget" and decision.allowance.risk_percent == 0.3
        assert decision.approved

    def test_an_exhausted_budget_denies_with_its_own_reason(self) -> None:
        profile = RiskProfile(max_open_risk_percent=10.0, max_correlated_risk_percent=10.0)
        decision = decide(
            context(**account(0.0, open_risk_percent=5.0), profile=profile), eur_intent(), review_for("EURUSDm")
        )
        assert not decision.approved and "risk_budget_exhausted" in decision.reasons

    def test_the_remaining_weekly_budget_can_be_stricter_than_the_grid(self) -> None:
        # The week started 9.5 % up on a flat day: 0.5 % of the week's 10 % is left and the total drawdown is nil.
        decision = decide(
            context(**account(0.0, week_start_equity=INITIAL * 1.095)), eur_intent(), review_for("EURUSDm")
        )
        assert decision.allowance is not None
        assert decision.allowance.binding_cap == "weekly_budget" and decision.allowance.risk_percent == 0.5


class TestProviderRules:
    """§7: one strategy, one risk grid for both accounts; a stricter external rule always wins."""

    def rules(self, provider: Provider):
        if provider is Provider.FTMO:
            params = ProfileParams(
                account_type=AccountType.PROP_CHALLENGE,
                challenge=FtmoChallenge(type="2-step", account_size=10_000, phase="challenge"),
            )
        else:
            params = ProfileParams(account_type=AccountType.DIRECT, reference_balance=10_000.0)
        return default_rules(provider, params).risk_profile

    def test_exness_and_ftmo_share_the_internal_rules(self) -> None:
        exness, ftmo = self.rules(Provider.EXNESS), self.rules(Provider.FTMO)
        for field in ("dynamic", "max_trades_per_day", "max_risk_per_trade_percent", "max_open_risk_percent"):
            assert getattr(exness, field) == getattr(ftmo, field), field
        assert exness.positions == ftmo.positions
        assert exness.drawdown.weekly_loss_limit_percent == ftmo.drawdown.weekly_loss_limit_percent == 10.0
        assert exness.drawdown.daily_loss_limit_percent == ftmo.drawdown.daily_loss_limit_percent == 5.0

    def test_ftmo_measures_against_the_challenge_size_not_the_balance(self) -> None:
        assert self.rules(Provider.FTMO).drawdown.reference_balance == 10_000

    def test_the_same_account_state_gives_the_same_allowance_on_both_providers(self) -> None:
        results = []
        for provider in (Provider.EXNESS, Provider.FTMO):
            profile = self.rules(provider)
            state = evaluate_risk_state(inputs(**account(-3.0), profile=profile))
            results.append((state.allowance.risk_percent, state.allowance.binding_cap))
        assert results[0] == results[1] == (0.2, "grid")

    def test_a_stricter_provider_limit_beats_the_internal_grid(self) -> None:
        # A provider whose daily loss is 1.2 % (stricter than our 5 %): after −1 % today only 0.2 % is left to risk,
        # though the grid says 1 %.
        strict = RiskProfile(drawdown=DrawdownPolicy(daily_loss_limit_percent=1.2, reference_balance=INITIAL))
        state = evaluate_risk_state(inputs(**account(-1.0, day_start_equity=INITIAL), profile=strict))
        assert state.allowance.binding_cap == "daily_budget" and state.allowance.risk_percent == 0.2

    def test_provider_ceilings_clamp_looser_internal_limits(self) -> None:
        ftmo_challenge = FtmoChallenge(type="2-step", account_size=10_000, phase="challenge")
        ceilings = provider_ceilings(ftmo_challenge)
        assert (ceilings.daily_loss_percent, ceilings.max_drawdown_percent) == (5.0, 10.0)
        loose = AccountRules(
            risk_profile=RiskProfile(
                drawdown=DrawdownPolicy(daily_loss_limit_percent=9.0, max_drawdown_limit_percent=20.0)
            ),
            trading_rules=TradingRules(),
            execution_profile=ExecutionProfile(),
        )
        drawdown = apply_provider_ceilings(loose, ceilings).risk_profile.drawdown
        assert (drawdown.daily_loss_limit_percent, drawdown.max_drawdown_limit_percent) == (5.0, 10.0)

    def test_stricter_internal_limits_and_unsourced_phases_are_left_alone(self) -> None:
        strict = AccountRules(
            risk_profile=RiskProfile(drawdown=DrawdownPolicy(daily_loss_limit_percent=2.0)),
            trading_rules=TradingRules(),
            execution_profile=ExecutionProfile(),
        )
        challenge = FtmoChallenge(type="2-step", account_size=10_000, phase="challenge")
        assert apply_provider_ceilings(strict, provider_ceilings(challenge)) is not None
        assert (
            apply_provider_ceilings(strict, provider_ceilings(challenge)).risk_profile.drawdown.daily_loss_limit_percent
            == 2.0
        )
        funded = FtmoChallenge(type="1-step", account_size=10_000, phase="funded")
        assert provider_ceilings(funded).daily_loss_percent is None  # not sourced: not guessed
        assert provider_ceilings(None).daily_loss_percent is None
        loose = strict.model_copy(
            update={"risk_profile": RiskProfile(drawdown=DrawdownPolicy(daily_loss_limit_percent=9.0))}
        )
        assert apply_provider_ceilings(loose, provider_ceilings(None)) is loose

    def test_the_position_limit_is_the_strictest_of_profile_and_provider(self) -> None:
        profile = RiskProfile(positions=PositionLimits(max_open_positions=2))
        assert can_i_trade(context(profile=profile, open_positions=2), "EURUSDm").reasons == ["position_limit_reached"]


class TestWeekAnchor:
    def test_monday_midnight_server_time(self) -> None:
        # Wednesday 2026-01-07 14:00 UTC, broker at UTC+2: the week began Monday 2026-01-05 00:00 +02:00 = Sunday 22:00 UTC.
        wednesday = datetime(2026, 1, 7, 14, 0, tzinfo=UTC)
        assert resolve_week_start_utc(wednesday, 120) == datetime(2026, 1, 4, 22, 0, tzinfo=UTC)

    def test_the_server_clock_decides_not_utc(self) -> None:
        # Sunday 23:30 UTC is already Monday 01:30 for a UTC+2 broker: a new week there, still the old one in UTC.
        sunday_night = datetime(2026, 1, 11, 23, 30, tzinfo=UTC)
        assert resolve_week_start_utc(sunday_night, 120) == datetime(2026, 1, 11, 22, 0, tzinfo=UTC)
        assert resolve_week_start_utc(sunday_night, 0) == datetime(2026, 1, 5, 0, 0, tzinfo=UTC)

    def test_dst_offset_moves_the_boundary(self) -> None:
        summer = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)  # a broker at UTC+3 in summer
        assert resolve_week_start_utc(summer, 180) == datetime(2026, 7, 5, 21, 0, tzinfo=UTC)

    def test_idempotent_inside_the_week(self) -> None:
        first = resolve_week_start_utc(datetime(2026, 1, 6, 9, 0, tzinfo=UTC), 120)
        last = resolve_week_start_utc(datetime(2026, 1, 10, 20, 0, tzinfo=UTC), 120)
        assert first == last


def test_spec_fixture_sanity() -> None:
    # The worked example above relies on these two figures.
    assert EURUSD.tick_size == 0.00001 and XAUUSD.tick_value_loss == 0.1
