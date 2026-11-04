"""The provider's market restrictions: news windows, market breaks, and the daily request budget (ADR 0036).

Three rules of a provider's contract that depend on the **product**, never on the provider alone — FTMO restricts news and breaks on a
funded Standard account and on nothing during Challenge, Verification or on a Swing account — and that each need a fact the core does
not always have: the restricted calendar, the schedule of the market's breaks, the number of requests sent today. Each evaluator
answers ``not_applicable``, ``clear``, ``blocked`` or ``unknown``; **``unknown`` blocks** (« en cas de doute, bloquer l'action
concernée »). A rule that applies and a fact that is missing is a refusal with the reason, never a pass.

Closing a position is never refused here: these rules bound *entries*. Whether a break obliges a position to be closed is its own
question (``closing_plan_before_break``) and is answered separately from any general halt, which does not close everything (ADR 0033).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from trading_os.domain.primitives import DomainModel
from trading_os.domain.providers.rules import NewsAction, NewsRestrictionRule, ProviderRuleSet

Status = Literal["not_applicable", "clear", "blocked", "unknown"]

NEWS_RESTRICTION = "provider_news_restriction"
NEWS_CALENDAR_UNKNOWN = "provider_news_calendar_unknown"
NEWS_SYMBOL_UNCLASSIFIED = "provider_news_symbol_unclassified"
OVERNIGHT_RESTRICTION = "provider_overnight_restriction"
OVERNIGHT_SCHEDULE_UNKNOWN = "provider_overnight_schedule_unknown"
REQUEST_BUDGET_EXHAUSTED = "provider_request_budget_exhausted"
REQUEST_COUNT_UNKNOWN = "provider_request_count_unknown"

# Personal prudence, not provider rules: no entry within this long of a restricted break, nor once this share of the day's requests is gone.
DEFAULT_ENTRY_CUTOFF_MINUTES = 30
REQUEST_WARNING_FRACTION = 0.75
REQUEST_ENTRY_BLOCK_FRACTION = 0.90

_FIAT = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CHF",
        "CAD",
        "AUD",
        "NZD",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "MXN",
        "ZAR",
        "TRY",
        "SGD",
        "HKD",
    }
)


# --------------------------------------------------------------------------------------------------------------------- news
class RestrictedEvent(DomainModel):
    """One release the provider marks as restricted. ``source`` says where we learned of it: the provider's own calendar, or a
    person. A generic economic calendar is not enough to authorise an action (ADR 0036): it can only add events, never clear one."""

    event_id: str
    name: str
    currency: str  # a currency code, or ``OIL`` for crude-oil releases
    scheduled_at: datetime  # UTC
    source: str


class NewsDecision(DomainModel):
    status: Status
    action: NewsAction
    symbol: str
    rule_set_id: str | None
    currencies_affecting: tuple[str, ...] = ()
    event: RestrictedEvent | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    reason: str | None = None
    detail: str = ""

    @property
    def blocked(self) -> bool:
        return self.status in ("blocked", "unknown")


def _normalise(symbol: str) -> str:
    return symbol.upper().removesuffix(".CASH")


def currencies_affecting(
    rule: NewsRestrictionRule, symbol: str, base: str | None, profit: str | None
) -> tuple[tuple[str, ...], bool]:
    """The release currencies that restrict ``symbol``, and whether the symbol could be classified at all. A forex pair is restricted by
    either of its currencies the provider lists; anything else only by what the provider names for it."""
    affecting: set[str] = set()
    classified = False
    if base in _FIAT and profit in _FIAT:
        classified = True
        affecting |= {code for code in (base, profit) if code in rule.forex_currencies}
    name = _normalise(symbol)
    for currency, symbols in rule.symbols_by_currency.items():
        if name in symbols:
            classified = True
            affecting.add(currency)
    return tuple(sorted(affecting)), classified


def evaluate_news_restriction(
    rule_set: ProviderRuleSet | None,
    *,
    now: datetime,
    symbol: str,
    base_currency: str | None,
    profit_currency: str | None,
    action: NewsAction,
    events: Sequence[RestrictedEvent] | None,
    covered_currencies: frozenset[str] | None,
) -> NewsDecision:
    """May ``action`` on ``symbol`` happen now? ``events`` is the provider's restricted calendar (``None`` = we have none) and
    ``covered_currencies`` the currencies that calendar is complete for: a currency that restricts the symbol and is not covered is a
    doubt, and a doubt blocks."""
    rule = rule_set.news if rule_set is not None else None
    set_id = rule_set.rule_set_id if rule_set is not None else None
    if rule is None:
        return NewsDecision(
            status="not_applicable",
            action=action,
            symbol=symbol,
            rule_set_id=set_id,
            detail="no news restriction applies to this product",
        )
    if action not in rule.actions:
        return NewsDecision(
            status="clear",
            action=action,
            symbol=symbol,
            rule_set_id=set_id,
            detail=f"{action} is not a restricted action",
        )
    affecting, classified = currencies_affecting(rule, symbol, base_currency, profit_currency)
    if events is None or covered_currencies is None:
        return NewsDecision(
            status="unknown",
            action=action,
            symbol=symbol,
            rule_set_id=set_id,
            currencies_affecting=affecting,
            reason=NEWS_CALENDAR_UNKNOWN,
            detail="the provider's restricted-news calendar is not loaded: failing closed",
        )
    before, after = timedelta(seconds=rule.before_seconds), timedelta(seconds=rule.after_seconds)
    in_window = [event for event in events if event.scheduled_at - before <= now <= event.scheduled_at + after]
    if not classified:
        # We cannot tell which releases touch this symbol: any restricted release in the window is a doubt.
        if in_window:
            event = in_window[0]
            return NewsDecision(
                status="blocked",
                action=action,
                symbol=symbol,
                rule_set_id=set_id,
                event=event,
                window_start=event.scheduled_at - before,
                window_end=event.scheduled_at + after,
                reason=NEWS_SYMBOL_UNCLASSIFIED,
                detail=f"{symbol} cannot be classified and {event.name} ({event.currency}) is in its window: blocking",
            )
        return NewsDecision(
            status="clear",
            action=action,
            symbol=symbol,
            rule_set_id=set_id,
            detail=f"{symbol} is not classified but no restricted release is in the window",
        )
    uncovered = [currency for currency in affecting if currency not in covered_currencies]
    if uncovered:
        return NewsDecision(
            status="unknown",
            action=action,
            symbol=symbol,
            rule_set_id=set_id,
            currencies_affecting=affecting,
            reason=NEWS_CALENDAR_UNKNOWN,
            detail=f"the calendar does not cover {', '.join(uncovered)}: failing closed",
        )
    hits = [event for event in in_window if event.currency in affecting]
    if hits:
        event = min(hits, key=lambda item: abs((item.scheduled_at - now).total_seconds()))
        return NewsDecision(
            status="blocked",
            action=action,
            symbol=symbol,
            rule_set_id=set_id,
            currencies_affecting=affecting,
            event=event,
            window_start=event.scheduled_at - before,
            window_end=event.scheduled_at + after,
            reason=NEWS_RESTRICTION,
            detail=f"{event.name} ({event.currency}) at {event.scheduled_at:%H:%M}Z restricts {symbol}: ±{rule.before_seconds // 60} min",
        )
    return NewsDecision(
        status="clear",
        action=action,
        symbol=symbol,
        rule_set_id=set_id,
        currencies_affecting=affecting,
        detail="no restricted release in the window",
    )


# ------------------------------------------------------------------------------------------------------------------- breaks
class MarketBreak(DomainModel):
    start: datetime  # UTC
    end: datetime
    symbol: str | None = None

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


class OvernightDecision(DomainModel):
    status: Status
    rule_set_id: str | None
    next_break: MarketBreak | None = None
    reason: str | None = None
    detail: str = ""

    @property
    def blocked(self) -> bool:
        return self.status in ("blocked", "unknown")


def _next_long_break(rule_set: ProviderRuleSet, now: datetime, breaks: Sequence[MarketBreak]) -> MarketBreak | None:
    threshold = rule_set.overnight.break_longer_than_hours or 0.0
    candidates = [item for item in breaks if item.hours > threshold and item.end > now]
    return min(candidates, key=lambda item: item.start) if candidates else None


def evaluate_entry_before_break(
    rule_set: ProviderRuleSet | None,
    *,
    now: datetime,
    breaks: Sequence[MarketBreak] | None,
    cutoff_minutes: int = DEFAULT_ENTRY_CUTOFF_MINUTES,
) -> OvernightDecision:
    """A product that must be flat before a long break may not open a position about to be caught by one."""
    set_id = rule_set.rule_set_id if rule_set is not None else None
    if rule_set is None or not rule_set.overnight.restricted:
        return OvernightDecision(
            status="not_applicable", rule_set_id=set_id, detail="positions may cross a break on this product"
        )
    if breaks is None:
        return OvernightDecision(
            status="unknown",
            rule_set_id=set_id,
            reason=OVERNIGHT_SCHEDULE_UNKNOWN,
            detail="the market's break schedule is unknown (the Python terminal API gives no sessions): failing closed",
        )
    upcoming = _next_long_break(rule_set, now, breaks)
    if upcoming is None:
        return OvernightDecision(status="clear", rule_set_id=set_id, detail="no long break ahead in the known schedule")
    if upcoming.start <= now:
        return OvernightDecision(
            status="blocked",
            rule_set_id=set_id,
            next_break=upcoming,
            reason=OVERNIGHT_RESTRICTION,
            detail="a long market break is in progress",
        )
    minutes = (upcoming.start - now).total_seconds() / 60
    if minutes < cutoff_minutes:
        return OvernightDecision(
            status="blocked",
            rule_set_id=set_id,
            next_break=upcoming,
            reason=OVERNIGHT_RESTRICTION,
            detail=f"a {upcoming.hours:.1f} h break begins in {minutes:.0f} min: this product must be flat before it",
        )
    return OvernightDecision(
        status="clear",
        rule_set_id=set_id,
        next_break=upcoming,
        detail=f"next long break in {minutes:.0f} min",
    )


class BreakClosingPlan(DomainModel):
    """Whether open positions must be closed because a long break is coming — a rule of its own, not a reaction to a halt."""

    applies: bool
    due: bool
    known: bool  # False = the schedule is unknown, so nothing can be said (the caller must not close blindly, nor assume flat)
    must_close_by: datetime | None = None
    next_break: MarketBreak | None = None
    detail: str = ""


def closing_plan_before_break(
    rule_set: ProviderRuleSet | None, *, now: datetime, breaks: Sequence[MarketBreak] | None, lead_minutes: int
) -> BreakClosingPlan:
    if rule_set is None or not rule_set.overnight.restricted:
        return BreakClosingPlan(
            applies=False, due=False, known=True, detail="positions may cross a break on this product"
        )
    if breaks is None:
        return BreakClosingPlan(
            applies=True,
            due=False,
            known=False,
            detail="the break schedule is unknown: it must be known to close in time",
        )
    upcoming = _next_long_break(rule_set, now, breaks)
    if upcoming is None:
        return BreakClosingPlan(applies=True, due=False, known=True, detail="no long break ahead")
    must_close_by = upcoming.start - timedelta(minutes=lead_minutes)
    return BreakClosingPlan(
        applies=True,
        due=now >= must_close_by,
        known=True,
        must_close_by=must_close_by,
        next_break=upcoming,
        detail=f"flat by {must_close_by:%H:%M}Z for the {upcoming.hours:.1f} h break",
    )


# ----------------------------------------------------------------------------------------------------------------- requests
class RequestBudget(DomainModel):
    status: Literal["not_applicable", "ok", "warning", "blocked", "unknown"]
    limit: int | None = None
    used: int | None = None
    remaining: int | None = None
    reason: str | None = None
    detail: str = ""

    @property
    def blocks_entries(self) -> bool:
        return self.status in ("blocked", "unknown")


def evaluate_request_budget(rule_set: ProviderRuleSet | None, *, used_today: int | None) -> RequestBudget:
    """Server requests (orders sent, modified, closed, cancelled) against the provider's daily ceiling. Overloading the server is a
    forbidden practice: entries stop before the ceiling, with room left to close what is open. Closing is never refused."""
    limit = rule_set.max_requests_per_day if rule_set is not None else None
    if limit is None:
        return RequestBudget(status="not_applicable", detail="the provider states no request ceiling for this product")
    if used_today is None:
        return RequestBudget(
            status="unknown", limit=limit, reason=REQUEST_COUNT_UNKNOWN, detail="today's request count cannot be read"
        )
    remaining = limit - used_today
    figures = f"{used_today}/{limit} requests today"
    if used_today >= limit * REQUEST_ENTRY_BLOCK_FRACTION:
        return RequestBudget(
            status="blocked",
            limit=limit,
            used=used_today,
            remaining=remaining,
            reason=REQUEST_BUDGET_EXHAUSTED,
            detail=figures,
        )
    status: Literal["ok", "warning"] = "warning" if used_today >= limit * REQUEST_WARNING_FRACTION else "ok"
    return RequestBudget(status=status, limit=limit, used=used_today, remaining=remaining, detail=figures)


__all__ = [
    "DEFAULT_ENTRY_CUTOFF_MINUTES",
    "NEWS_CALENDAR_UNKNOWN",
    "NEWS_RESTRICTION",
    "NEWS_SYMBOL_UNCLASSIFIED",
    "OVERNIGHT_RESTRICTION",
    "OVERNIGHT_SCHEDULE_UNKNOWN",
    "REQUEST_BUDGET_EXHAUSTED",
    "REQUEST_COUNT_UNKNOWN",
    "BreakClosingPlan",
    "MarketBreak",
    "NewsDecision",
    "OvernightDecision",
    "RequestBudget",
    "RestrictedEvent",
    "closing_plan_before_break",
    "currencies_affecting",
    "evaluate_entry_before_break",
    "evaluate_news_restriction",
    "evaluate_request_budget",
]
