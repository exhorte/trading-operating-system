"""The provider's side joins the Risk Engine (ADR 0036): one gate, more budgets, more reasons — and never a looser answer."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from tests.support.provider_fixtures import exness_standard, ftmo_account_2step, ftmo_challenge_1step, ftmo_swing
from tests.unit.domain.risk.fixtures import NOW, SPECS, inputs
from tests.unit.domain.risk.test_official_limits import eur_intent, review_for
from tests.unit.domain.test_instrument_specification import terminal_reply
from trading_os.domain.market.instrument import specification_from_terminal
from trading_os.domain.providers.context import ProviderContext
from trading_os.domain.providers.identity import identify_account
from trading_os.domain.providers.loss_floors import LossReference, day_start_utc, evaluate_loss_state
from trading_os.domain.providers.restrictions import (
    MarketBreak,
    RestrictedEvent,
    evaluate_entry_before_break,
    evaluate_news_restriction,
    evaluate_request_budget,
)
from trading_os.domain.providers.rules import ProviderProduct, rule_set_for
from trading_os.domain.risk.decision import HealthFlags, IntentReview, TradingContext, can_i_trade, decide
from trading_os.domain.risk.evaluate import evaluate_risk_state
from trading_os.domain.risk.state import RiskMode

PRAGUE = "Europe/Prague"
TODAY = date(2026, 1, 5)  # NOW is Monday 2026-01-05 10:00 UTC = 11:00 in Prague
CAPITAL = 100_000.0


def reference(balance: float) -> LossReference:
    return LossReference(
        local_date=TODAY,
        timezone=PRAGUE,
        reference_balance=balance,
        recorded_at=day_start_utc(TODAY, PRAGUE),
        source="observed",
        rule_set_id="test",
    )


def provider_context(
    facts, *, equity: float = CAPITAL, daily_reference: float | None = CAPITAL, **extra: object
) -> ProviderContext:
    identification = identify_account(facts)
    rule_set = rule_set_for(identification.rules_product)
    refs = [reference(daily_reference)] if daily_reference is not None else []
    loss = evaluate_loss_state(
        rule_set,
        initial_capital=CAPITAL,
        equity=equity,
        now=NOW,
        daily_reference=refs[-1] if refs else None,
        references=refs,
        references_complete=True,
    )
    return ProviderContext(identification=identification, rule_set=rule_set, loss=loss, **extra)  # type: ignore[arg-type]


def trading_context(provider: ProviderContext | None, **risk: object) -> TradingContext:
    base = {
        "initial_balance": CAPITAL,
        "balance": CAPITAL,
        "equity": CAPITAL,
        "day_start_equity": CAPITAL,
        "week_start_equity": CAPITAL,
    }
    base.update(risk)
    if provider is not None and provider.loss is not None:
        base["provider_loss"] = provider.loss
    return TradingContext(risk=inputs(**base), health=HealthFlags(), specs=SPECS, provider=provider)


class TestNothingAsksNothingChanges:
    def test_without_a_provider_context_the_engine_answers_exactly_as_before(self) -> None:
        assert can_i_trade(trading_context(None), symbol="EURUSDm").reasons == []

    def test_a_clean_identified_account_adds_no_reason(self) -> None:
        for facts in (exness_standard(), ftmo_account_2step()):
            context = trading_context(provider_context(facts, news=None))
            result = can_i_trade(context, symbol="EURUSDm")
            assert result.reasons == [], result.reasons
            assert any(check.check_id == "provider_identity" and check.ok for check in result.checks)


class TestIdentityIsAGate:
    def test_a_product_nobody_declared_refuses_the_entry_and_says_why(self) -> None:
        from tests.support.provider_fixtures import ftmo

        result = can_i_trade(trading_context(provider_context(ftmo(declared=False))), symbol="EURUSDm")
        assert result.decision == "DENIED" and "account_product_unknown" in result.reasons
        assert any(check.reason == "account_product_unknown" and "declare" in check.detail for check in result.checks)

    def test_swing_is_refused_because_its_loss_rules_are_not_sourced(self) -> None:
        result = can_i_trade(trading_context(provider_context(ftmo_swing(), daily_reference=None)), symbol="EURUSDm")
        assert "provider_rules_unsourced" in result.reasons

    def test_every_blocker_is_its_own_reason(self) -> None:
        facts = exness_standard(real=True, declared_environment=None, observed_suffixes=())
        result = can_i_trade(trading_context(provider_context(facts)), symbol="EURUSDm")
        assert "account_product_unknown" in result.reasons

    def test_an_unidentified_account_cannot_be_rescued_by_a_clean_risk_state(self) -> None:
        context = trading_context(
            provider_context(exness_standard(server="Other-Demo", company="Other", terminal_company="Other"))
        )
        assert can_i_trade(context, symbol="EURUSDm").decision == "DENIED"


class TestProviderLossFloors:
    def test_a_breach_blocks_locks_and_names_the_floor(self) -> None:
        # 1-Step: floor 97 000 (100 000 − 3 %). Equity 96 900.
        provider = provider_context(ftmo_challenge_1step(), equity=96_900.0)
        context = trading_context(provider, equity=96_900.0, balance=96_900.0)
        result = can_i_trade(context, symbol="EURUSDm")
        assert "provider_daily_loss_breached" in result.reasons
        state = evaluate_risk_state(context.risk.model_copy(update={"require_tick": True}))
        gate = next(g for g in state.gates if g.gate_id == "gate-provider-loss")
        assert gate.blocked and state.mode is RiskMode.LOCKED
        assert "Provider loss floor" in (state.lockout_reason or "")

    def test_an_unknown_reference_refuses_entries_without_a_lockout(self) -> None:
        provider = provider_context(ftmo_challenge_1step(), daily_reference=None)
        context = trading_context(provider)
        result = can_i_trade(context, symbol="EURUSDm")
        assert "provider_daily_reference_missing" in result.reasons
        state = evaluate_risk_state(context.risk)
        assert next(g for g in state.gates if g.gate_id == "gate-provider-loss").blocked is False
        assert state.mode is not RiskMode.LOCKED  # nothing was lost: something is not known

    def test_the_provider_budget_can_be_the_cap_that_binds(self) -> None:
        # The balance at midnight was 104 000 (a good day before); equity is now 102 200: +2.2 % → the grid says 1.5 %, but only
        # 1.2 % remains above the 1-Step daily floor (104 000 − 3 000 = 101 000 → 1 200 of room).
        provider = provider_context(ftmo_challenge_1step(), equity=102_200.0, daily_reference=104_000.0)
        context = trading_context(
            provider, equity=102_200.0, balance=102_200.0, day_start_equity=104_000.0, week_start_equity=104_000.0
        )
        allowance = evaluate_risk_state(context.risk).allowance
        assert allowance.status == "allowed"
        assert allowance.binding_cap == "provider_daily_budget" and allowance.risk_percent == 1.2

    def test_open_risk_counts_in_full_against_the_provider_floor(self) -> None:
        provider = provider_context(ftmo_challenge_1step(), equity=102_200.0, daily_reference=104_000.0)
        context = trading_context(
            provider,
            equity=102_200.0,
            balance=102_200.0,
            day_start_equity=104_000.0,
            week_start_equity=104_000.0,
            open_risk_percent=0.5,
        )
        assert evaluate_risk_state(context.risk).allowance.risk_percent == 0.7

    def test_the_provider_floor_never_raises_a_personal_limit(self) -> None:
        # Personal budget (5 % of a flat day) is wide; the provider cannot make it wider, only narrower.
        provider = provider_context(ftmo_challenge_1step())
        with_provider = evaluate_risk_state(trading_context(provider).risk).allowance
        without = evaluate_risk_state(trading_context(None).risk).allowance
        assert with_provider.risk_percent <= without.risk_percent

    def test_exness_has_no_provider_floor_and_the_gate_is_absent(self) -> None:
        provider = provider_context(exness_standard())
        state = evaluate_risk_state(trading_context(provider).risk)
        assert all(gate.gate_id != "gate-provider-loss" for gate in state.gates)


class TestMarketRestrictions:
    def clear_news(self, at: datetime) -> object:
        return evaluate_news_restriction(
            rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP),
            now=at,
            symbol="EURUSDm",
            base_currency="EUR",
            profit_currency="USD",
            action="open",
            events=[],
            covered_currencies=frozenset({"USD", "EUR"}),
        )

    def test_a_restricted_release_refuses_the_entry(self) -> None:
        event = RestrictedEvent(
            event_id="e", name="CPI", currency="USD", scheduled_at=NOW + timedelta(minutes=1), source="ftmo"
        )
        news = evaluate_news_restriction(
            rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP),
            now=NOW,
            symbol="EURUSD",
            base_currency="EUR",
            profit_currency="USD",
            action="open",
            events=[event],
            covered_currencies=frozenset({"USD", "EUR"}),
        )
        result = can_i_trade(trading_context(provider_context(ftmo_account_2step(), news=news)), symbol="EURUSDm")
        assert "provider_news_restriction" in result.reasons

    def test_a_calendar_we_do_not_have_refuses_the_entry_of_a_restricted_product(self) -> None:
        news = evaluate_news_restriction(
            rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP),
            now=NOW,
            symbol="EURUSD",
            base_currency="EUR",
            profit_currency="USD",
            action="open",
            events=None,
            covered_currencies=None,
        )
        result = can_i_trade(trading_context(provider_context(ftmo_account_2step(), news=news)), symbol="EURUSDm")
        assert "provider_news_calendar_unknown" in result.reasons

    def test_a_break_about_to_begin_refuses_the_entry(self) -> None:
        brk = MarketBreak(start=NOW + timedelta(minutes=10), end=NOW + timedelta(hours=30))
        overnight = evaluate_entry_before_break(rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP), now=NOW, breaks=[brk])
        result = can_i_trade(
            trading_context(provider_context(ftmo_account_2step(), overnight=overnight)), symbol="EURUSDm"
        )
        assert "provider_overnight_restriction" in result.reasons

    def test_an_exhausted_request_budget_refuses_entries(self) -> None:
        budget = evaluate_request_budget(rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP), used_today=1_900)
        result = can_i_trade(trading_context(provider_context(ftmo_account_2step(), requests=budget)), symbol="EURUSDm")
        assert "provider_request_budget_exhausted" in result.reasons

    def test_a_clear_decision_with_a_clear_calendar_stays_allowed(self) -> None:
        provider = provider_context(
            ftmo_account_2step(),
            news=self.clear_news(NOW),  # type: ignore[arg-type]
            requests=evaluate_request_budget(rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP), used_today=10),
        )
        assert can_i_trade(trading_context(provider), symbol="EURUSDm").decision == "ALLOWED"


class TestTheInstrumentSpecificationGate:
    def specification(self, **changes: object):
        spec = specification_from_terminal("EURUSDm", terminal_reply(**changes), now=NOW)
        assert spec is not None
        return spec

    def test_a_specification_with_what_an_order_needs_is_reviewed_as_usual(self) -> None:
        spec = self.specification()
        decision = decide(trading_context(None), eur_intent(), IntentReview(spec=spec, spread=0.00008))
        assert "instrument_specification_missing" not in decision.reasons

    def test_a_specification_with_holes_is_refused_and_names_them(self) -> None:
        raw = terminal_reply()
        del raw["filling_mode"], raw["trade_exemode"]
        spec = specification_from_terminal("EURUSDm", raw, now=NOW)
        assert spec is not None
        decision = decide(trading_context(None), eur_intent(), IntentReview(spec=spec, spread=0.00008))
        assert not decision.approved and "instrument_specification_missing" in decision.reasons
        check = next(c for c in decision.checks if c.reason == "instrument_specification_missing")
        assert "filling_mode" in check.detail and "execution_mode" in check.detail
        assert decision.sizing is None and decision.approved_volume is None

    def test_a_plain_symbol_spec_is_not_second_guessed(self) -> None:
        assert not decide(trading_context(None), eur_intent(), review_for("EURUSDm")).reasons


def test_the_personal_rules_still_decide_when_the_provider_is_silent() -> None:
    # The same numbers as the official-limits suite: 15 trades a day, whatever the provider says.
    provider = provider_context(ftmo_account_2step())
    context = trading_context(provider, trades_today=15)
    result = can_i_trade(context, symbol="EURUSDm")
    assert result.reasons == ["max_trades_reached"]
