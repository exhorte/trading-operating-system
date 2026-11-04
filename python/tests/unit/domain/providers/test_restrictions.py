"""News windows, market breaks and the request budget: product-dependent, and every missing fact blocks (ADR 0036)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_os.domain.providers.restrictions import (
    NEWS_CALENDAR_UNKNOWN,
    NEWS_RESTRICTION,
    NEWS_SYMBOL_UNCLASSIFIED,
    OVERNIGHT_RESTRICTION,
    OVERNIGHT_SCHEDULE_UNKNOWN,
    REQUEST_BUDGET_EXHAUSTED,
    REQUEST_COUNT_UNKNOWN,
    MarketBreak,
    RestrictedEvent,
    closing_plan_before_break,
    currencies_affecting,
    evaluate_entry_before_break,
    evaluate_news_restriction,
    evaluate_request_budget,
)
from trading_os.domain.providers.rules import ProviderProduct, ProviderRuleSet, rule_set_for

EVENT_AT = datetime(2026, 11, 6, 13, 30, tzinfo=UTC)  # a US release
ALL = frozenset({"USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "OIL"})


def rules(product: ProviderProduct) -> ProviderRuleSet:
    found = rule_set_for(product)
    assert found is not None
    return found


def nfp() -> RestrictedEvent:
    return RestrictedEvent(
        event_id="nfp", name="Non-Farm Employment Change", currency="USD", scheduled_at=EVENT_AT, source="ftmo-calendar"
    )


def news(
    symbol: str,
    base: str | None,
    profit: str | None,
    *,
    at: datetime,
    product: ProviderProduct = ProviderProduct.FTMO_ACCOUNT_2STEP,
    action: str = "open",
    events: list[RestrictedEvent] | None = None,
    covered: frozenset[str] | None = ALL,
):
    return evaluate_news_restriction(
        rules(product),
        now=at,
        symbol=symbol,
        base_currency=base,
        profit_currency=profit,
        action=action,  # type: ignore[arg-type]
        events=[nfp()] if events is None else events,
        covered_currencies=covered,
    )


class TestNewsWindows:
    def test_two_minutes_before_and_after_a_restricted_release_blocks_the_affected_pair(self) -> None:
        for offset, blocked in ((-121, False), (-120, True), (-30, True), (0, True), (120, True), (121, False)):
            decision = news("EURUSD", "EUR", "USD", at=EVENT_AT + timedelta(seconds=offset))
            assert decision.blocked is blocked, offset
        decision = news("EURUSD", "EUR", "USD", at=EVENT_AT)
        assert decision.reason == NEWS_RESTRICTION and decision.event is not None
        assert decision.window_start == EVENT_AT - timedelta(minutes=2) and decision.window_end == EVENT_AT + timedelta(
            minutes=2
        )
        assert "Non-Farm" in decision.detail

    def test_only_the_instruments_that_carry_the_currency_are_restricted(self) -> None:
        # The provider's own example: during NFP, EURGBP and AUDNZD may be traded, USDJPY and GBPUSD may not.
        assert not news("EURGBP", "EUR", "GBP", at=EVENT_AT).blocked
        assert not news("AUDNZD", "AUD", "NZD", at=EVENT_AT).blocked
        assert news("USDJPY", "USD", "JPY", at=EVENT_AT).blocked
        assert news("GBPUSD", "GBP", "USD", at=EVENT_AT).blocked

    def test_gold_and_us_indices_follow_the_dollar_and_oil_does_not(self) -> None:
        assert news("XAUUSD", "XAU", "USD", at=EVENT_AT).blocked
        for index in ("US500.cash", "US100.cash", "US30.cash", "US2000.cash", "DXY"):
            assert news(index, None, "USD", at=EVENT_AT).blocked, index
        assert not news("USOIL.cash", None, "USD", at=EVENT_AT).blocked  # only crude-oil releases restrict oil

    def test_a_crude_oil_release_restricts_oil_and_nothing_else(self) -> None:
        oil = RestrictedEvent(
            event_id="eia", name="Crude Oil Inventories", currency="OIL", scheduled_at=EVENT_AT, source="ftmo-calendar"
        )
        assert news("USOIL.cash", None, "USD", at=EVENT_AT, events=[oil]).blocked
        assert news("UKOIL.cash", None, "USD", at=EVENT_AT, events=[oil]).blocked
        assert not news("EURUSD", "EUR", "USD", at=EVENT_AT, events=[oil]).blocked

    def test_every_restricted_action_is_covered_and_others_are_not(self) -> None:
        for action in ("open", "close", "modify", "pending", "stop_loss", "take_profit"):
            assert news("EURUSD", "EUR", "USD", at=EVENT_AT, action=action).blocked, action

    def test_the_decision_names_what_it_decided_on(self) -> None:
        decision = news("EURUSD", "EUR", "USD", at=EVENT_AT)
        assert decision.symbol == "EURUSD" and decision.action == "open"
        assert decision.currencies_affecting == ("EUR", "USD")
        assert decision.rule_set_id == "FTMO_ACCOUNT_2STEP@2026-11-02"


class TestTheRestrictionDependsOnTheProduct:
    @pytest.mark.parametrize(
        "product",
        [
            ProviderProduct.FTMO_CHALLENGE_1STEP,
            ProviderProduct.FTMO_CHALLENGE_2STEP,
            ProviderProduct.FTMO_VERIFICATION,
            ProviderProduct.FTMO_SWING,
            ProviderProduct.EXNESS_STANDARD,
        ],
    )
    def test_evaluation_phases_swing_and_exness_are_not_restricted(self, product: ProviderProduct) -> None:
        decision = news("EURUSD", "EUR", "USD", at=EVENT_AT, product=product)
        assert decision.status == "not_applicable" and not decision.blocked

    @pytest.mark.parametrize(
        "product",
        [ProviderProduct.FTMO_ACCOUNT_1STEP, ProviderProduct.FTMO_ACCOUNT_2STEP, ProviderProduct.FTMO_INSTANT],
    )
    def test_the_funded_standard_products_are_restricted(self, product: ProviderProduct) -> None:
        assert news("EURUSD", "EUR", "USD", at=EVENT_AT, product=product).blocked

    def test_an_unknown_product_has_no_rule_set_and_so_nothing_is_claimed(self) -> None:
        decision = evaluate_news_restriction(
            None,
            now=EVENT_AT,
            symbol="EURUSD",
            base_currency="EUR",
            profit_currency="USD",
            action="open",
            events=None,
            covered_currencies=None,
        )
        assert decision.status == "not_applicable"  # the identity gate, not this one, refuses an unknown product


class TestDoubtBlocks:
    def test_no_calendar_at_all_blocks(self) -> None:
        decision = news("EURUSD", "EUR", "USD", at=EVENT_AT - timedelta(hours=5), events=[])
        assert decision.status == "clear"  # an empty but known calendar is not the same as none
        unknown = evaluate_news_restriction(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP),
            now=EVENT_AT - timedelta(hours=5),
            symbol="EURUSD",
            base_currency="EUR",
            profit_currency="USD",
            action="open",
            events=None,
            covered_currencies=None,
        )
        assert unknown.status == "unknown" and unknown.blocked and unknown.reason == NEWS_CALENDAR_UNKNOWN

    def test_a_calendar_that_does_not_cover_a_currency_of_the_pair_blocks(self) -> None:
        decision = news("GBPUSD", "GBP", "USD", at=EVENT_AT - timedelta(hours=5), events=[], covered=frozenset({"USD"}))
        assert decision.status == "unknown" and "GBP" in decision.detail

    def test_a_calendar_that_covers_them_clears_a_quiet_hour(self) -> None:
        decision = news("GBPUSD", "GBP", "USD", at=EVENT_AT - timedelta(hours=5))
        assert decision.status == "clear" and not decision.blocked

    def test_a_symbol_that_cannot_be_classified_blocks_only_when_a_release_is_in_the_window(self) -> None:
        quiet = news("MYSTERY", None, None, at=EVENT_AT - timedelta(hours=5))
        assert quiet.status == "clear"
        busy = news("MYSTERY", None, None, at=EVENT_AT)
        assert busy.blocked and busy.reason == NEWS_SYMBOL_UNCLASSIFIED

    def test_the_classification_of_a_pair(self) -> None:
        rule = rules(ProviderProduct.FTMO_ACCOUNT_2STEP).news
        assert rule is not None
        assert currencies_affecting(rule, "EURUSD", "EUR", "USD") == (("EUR", "USD"), True)
        assert currencies_affecting(rule, "USDJPY", "USD", "JPY") == (("USD",), True)
        assert currencies_affecting(rule, "XAUUSD", "XAU", "USD") == (("USD",), True)
        assert currencies_affecting(rule, "MYSTERY", None, None) == ((), False)


def make_break(start_hour: int, hours: float, day: int = 6) -> MarketBreak:
    start = datetime(2026, 11, day, start_hour, 0, tzinfo=UTC)
    return MarketBreak(start=start, end=start + timedelta(hours=hours))


class TestBreaks:
    now = datetime(2026, 11, 6, 20, 0, tzinfo=UTC)

    def test_a_funded_standard_account_may_not_open_into_a_long_break(self) -> None:
        result = evaluate_entry_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP), now=self.now, breaks=[make_break(20, 49, day=6)]
        )
        assert result.blocked is True  # the break has begun
        soon = evaluate_entry_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP), now=self.now, breaks=[make_break(20, 49)], cutoff_minutes=30
        )
        assert soon.reason == OVERNIGHT_RESTRICTION

    def test_far_from_the_break_it_is_clear(self) -> None:
        result = evaluate_entry_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP), now=self.now - timedelta(hours=3), breaks=[make_break(20, 49)]
        )
        assert result.status == "clear" and result.next_break is not None

    def test_inside_the_cutoff_it_is_blocked(self) -> None:
        result = evaluate_entry_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP), now=self.now - timedelta(minutes=20), breaks=[make_break(20, 49)]
        )
        assert result.status == "blocked" and result.reason == OVERNIGHT_RESTRICTION and "20 min" in result.detail

    def test_a_short_break_is_not_a_break(self) -> None:
        result = evaluate_entry_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP),
            now=self.now - timedelta(minutes=10),
            breaks=[make_break(20, 1.0)],
        )
        assert result.status == "clear" and result.next_break is None  # one hour is under the two-hour threshold

    def test_the_threshold_is_longer_than_two_hours_not_two_hours(self) -> None:
        exactly_two = evaluate_entry_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP),
            now=self.now - timedelta(minutes=10),
            breaks=[make_break(20, 2.0)],
        )
        assert exactly_two.status == "clear"

    def test_an_unknown_schedule_blocks_a_restricted_product(self) -> None:
        result = evaluate_entry_before_break(rules(ProviderProduct.FTMO_ACCOUNT_2STEP), now=self.now, breaks=None)
        assert result.status == "unknown" and result.reason == OVERNIGHT_SCHEDULE_UNKNOWN and result.blocked

    @pytest.mark.parametrize(
        "product",
        [
            ProviderProduct.FTMO_CHALLENGE_2STEP,
            ProviderProduct.FTMO_VERIFICATION,
            ProviderProduct.FTMO_SWING,
            ProviderProduct.EXNESS_STANDARD,
        ],
    )
    def test_the_other_products_may_cross_a_break_and_need_no_schedule(self, product: ProviderProduct) -> None:
        result = evaluate_entry_before_break(rules(product), now=self.now, breaks=None)
        assert result.status == "not_applicable" and not result.blocked
        plan = closing_plan_before_break(rules(product), now=self.now, breaks=None, lead_minutes=5)
        assert not plan.applies and not plan.due


class TestClosingBeforeABreak:
    def test_a_position_is_due_for_closing_once_the_lead_time_is_reached(self) -> None:
        brk = make_break(20, 49)
        early = closing_plan_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP),
            now=brk.start - timedelta(minutes=30),
            breaks=[brk],
            lead_minutes=5,
        )
        due = closing_plan_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP),
            now=brk.start - timedelta(minutes=5),
            breaks=[brk],
            lead_minutes=5,
        )
        assert (early.applies, early.due, early.known) == (True, False, True)
        assert due.due and due.must_close_by == brk.start - timedelta(minutes=5)

    def test_an_unknown_schedule_is_reported_unknown_so_nobody_closes_blindly_or_assumes_flat(self) -> None:
        plan = closing_plan_before_break(
            rules(ProviderProduct.FTMO_ACCOUNT_2STEP), now=EVENT_AT, breaks=None, lead_minutes=5
        )
        assert plan.applies and not plan.known and not plan.due


class TestRequestBudget:
    def test_the_provider_ceiling_is_two_thousand_requests_a_day(self) -> None:
        budget = evaluate_request_budget(rules(ProviderProduct.FTMO_ACCOUNT_2STEP), used_today=100)
        assert (budget.status, budget.limit, budget.remaining) == ("ok", 2_000, 1_900)

    def test_a_warning_then_a_stop_to_entries_before_the_ceiling(self) -> None:
        warning = evaluate_request_budget(rules(ProviderProduct.FTMO_ACCOUNT_2STEP), used_today=1_500)
        stop = evaluate_request_budget(rules(ProviderProduct.FTMO_ACCOUNT_2STEP), used_today=1_800)
        assert warning.status == "warning" and not warning.blocks_entries
        assert stop.status == "blocked" and stop.reason == REQUEST_BUDGET_EXHAUSTED and stop.blocks_entries
        assert stop.remaining == 200  # room left to close what is open

    def test_an_unknown_count_blocks_entries(self) -> None:
        budget = evaluate_request_budget(rules(ProviderProduct.FTMO_ACCOUNT_2STEP), used_today=None)
        assert budget.status == "unknown" and budget.reason == REQUEST_COUNT_UNKNOWN and budget.blocks_entries

    def test_a_product_with_no_stated_ceiling_has_none(self) -> None:
        budget = evaluate_request_budget(rules(ProviderProduct.EXNESS_STANDARD), used_today=None)
        assert budget.status == "not_applicable" and not budget.blocks_entries
