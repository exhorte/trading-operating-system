"""The provider's loss floors, computed the way the provider computes them (ADR 0036) — kept apart from the personal limits.

A prop contract does not say « lose at most 5 % today ». It says: *the equity may not fall below a floor*, and the floor is built from
a **balance recorded at a precise instant** (00:00 Central European (Summer) Time), not from the equity at some moment the core
happened to see:

* daily floor = balance recorded at 00:00 of the day − the daily amount (a percentage of the **initial** capital);
* maximum floor, ``STATIC_INITIAL`` = initial capital − the maximum amount;
* maximum floor, ``TRAILING_EOD_BALANCE`` = the highest 00:00 balance ever recorded (or the initial capital, if higher) − the maximum
  amount: it only rises.

Equity is what is tested: balance + floating P/L ± swaps − commissions.

Nothing here reads a clock or a database. The caller passes the references it persisted; a reference that is missing, stale or
incomplete makes the state ``unknown``, and ``unknown`` is refusal (« en cas de référence manquante ou incohérente, bloquer les
nouvelles entrées »). Nothing re-derives a reference from the current balance: that would let a restart, a reconnection or a change
of settings reset the limit.

The personal limits (ADR 0019) are untouched and still apply. Both are tested; the stricter one decides.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from trading_os.domain.primitives import DomainModel
from trading_os.domain.providers.rules import LossMethod, ProviderRuleSet

ReferenceKind = Literal["daily"]
ReferenceSource = Literal["observed", "reconstructed"]
LossStatus = Literal["not_applicable", "ok", "unknown", "breached"]

# Stable reason codes (they reach the Risk Engine's refusal list and the cockpit).
INITIAL_CAPITAL_MISSING = "provider_initial_capital_missing"
EQUITY_UNKNOWN = "provider_equity_unknown"
DAILY_REFERENCE_MISSING = "provider_daily_reference_missing"
DAILY_REFERENCE_STALE = "provider_daily_reference_stale"
MAX_REFERENCE_INCOMPLETE = "provider_max_reference_incomplete"
MAX_METHOD_UNSUPPORTED = "provider_max_method_unsupported"
DAILY_LOSS_BREACHED = "provider_daily_loss_breached"
MAX_LOSS_BREACHED = "provider_max_loss_breached"


class LossReference(DomainModel):
    """The balance recorded at 00:00 of ``local_date`` in ``timezone``. The latest of them is the daily reference; the highest of
    all of them is the trailing maximum's reference. Append-only on the persistence side: the first one recorded for a day stays."""

    kind: ReferenceKind = "daily"
    local_date: date
    timezone: str
    reference_balance: float
    recorded_at: datetime
    source: ReferenceSource
    rule_set_id: str


class CashFlow(DomainModel):
    """What one deal did to the balance (profit + commission + swap + fee; a deposit or a withdrawal is a flow like any other)."""

    at: datetime
    amount: float


class ProviderLossState(DomainModel):
    status: LossStatus
    rule_set_id: str | None = None
    rule_version: str | None = None
    timezone: str | None = None
    initial_capital: float | None = None
    equity: float | None = None
    # daily
    daily_reference_balance: float | None = None
    daily_reference_at: datetime | None = None  # the instant 00:00 local time stands for, in UTC
    daily_loss_amount: float | None = None
    daily_floor: float | None = None
    daily_remaining: float | None = None  # equity − floor, in account currency
    # maximum
    max_method: LossMethod | None = None
    max_reference_balance: float | None = None
    max_loss_amount: float | None = None
    max_floor: float | None = None
    max_remaining: float | None = None
    # the accounting the equity is made of, when the caller knows it (never filled in with a guess)
    floating_pl: float | None = None
    realized_pl: float | None = None
    commissions: float | None = None
    swaps: float | None = None
    reasons: tuple[str, ...] = ()
    detail: str = ""

    @property
    def blocks_entries(self) -> bool:
        return self.status in ("unknown", "breached")


def local_day(now: datetime, timezone: str) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


def day_start_utc(day: date, timezone: str) -> datetime:
    """The UTC instant at which ``day`` begins in ``timezone`` (00:00 local; the zone's own rules handle the clock change)."""
    zone = ZoneInfo(timezone)
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(ZoneInfo("UTC"))


def balance_at(instant: datetime, current_balance: float, flows: Sequence[CashFlow]) -> float:
    """The balance at ``instant``, rebuilt from the balance now and everything that moved it since. Floating P/L is not in a balance,
    so a position open across ``instant`` does not matter — which is why a balance can be rebuilt after a restart where an equity
    cannot. The caller must hand over **every** flow after ``instant``; a partial history gives a wrong balance, never an unknown one."""
    return round(current_balance - sum(flow.amount for flow in flows if flow.at > instant), 2)


def reference_from_flows(
    day: date,
    *,
    timezone: str,
    current_balance: float,
    flows: Sequence[CashFlow],
    recorded_at: datetime,
    rule_set_id: str,
) -> LossReference:
    start = day_start_utc(day, timezone)
    return LossReference(
        local_date=day,
        timezone=timezone,
        reference_balance=balance_at(start, current_balance, flows),
        recorded_at=recorded_at,
        source="reconstructed",
        rule_set_id=rule_set_id,
    )


def _unknown(rule_set: ProviderRuleSet, reasons: Sequence[str], detail: str, **known: object) -> ProviderLossState:
    return ProviderLossState(
        status="unknown",
        rule_set_id=rule_set.rule_set_id,
        rule_version=rule_set.version,
        reasons=tuple(reasons),
        detail=detail,
        **known,
    )


def evaluate_loss_state(
    rule_set: ProviderRuleSet | None,
    *,
    initial_capital: float | None,
    equity: float | None,
    now: datetime,
    daily_reference: LossReference | None,
    references: Sequence[LossReference] = (),
    references_complete: bool = False,
    floating_pl: float | None = None,
    realized_pl: float | None = None,
    commissions: float | None = None,
    swaps: float | None = None,
) -> ProviderLossState:
    """The provider's two floors against the equity. ``references`` is every recorded 00:00 balance, ``references_complete`` says there
    is no day missing from it since the account began (only the trailing maximum needs that)."""
    if rule_set is None or not rule_set.requires_loss_references:
        return ProviderLossState(status="not_applicable", detail="the provider imposes no loss floor on this product")
    daily_rule, max_rule = rule_set.daily_loss, rule_set.max_loss
    assert (
        daily_rule is not None and max_rule is not None
    )  # every product with loss references has both (checked by the registry's tests)
    accounting = {"floating_pl": floating_pl, "realized_pl": realized_pl, "commissions": commissions, "swaps": swaps}
    if initial_capital is None or initial_capital <= 0:
        return _unknown(
            rule_set,
            [INITIAL_CAPITAL_MISSING],
            "no initial capital recorded: the provider's limits are percentages of it",
            timezone=daily_rule.timezone,
            equity=equity,
            **accounting,
        )
    if equity is None or equity <= 0:
        return _unknown(
            rule_set,
            [EQUITY_UNKNOWN],
            "no equity reading",
            timezone=daily_rule.timezone,
            initial_capital=initial_capital,
            **accounting,
        )

    today = local_day(now, daily_rule.timezone)
    reasons: list[str] = []
    daily_amount = round(initial_capital * daily_rule.percent / 100, 2)
    max_amount = round(initial_capital * max_rule.percent / 100, 2)
    daily_floor: float | None = None
    daily_reference_balance: float | None = None
    daily_at: datetime | None = None

    if daily_reference is None:
        reasons.append(DAILY_REFERENCE_MISSING)
    elif daily_reference.local_date != today:
        reasons.append(DAILY_REFERENCE_STALE)
    else:
        daily_reference_balance = daily_reference.reference_balance
        daily_floor = round(daily_reference_balance - daily_amount, 2)
        daily_at = day_start_utc(today, daily_rule.timezone)

    max_reference: float | None = None
    max_floor: float | None = None
    if max_rule.method is LossMethod.STATIC_INITIAL:
        max_reference = initial_capital
    elif max_rule.method is LossMethod.TRAILING_EOD_BALANCE:
        if not references_complete or daily_reference is None or daily_reference.local_date != today:
            reasons.append(MAX_REFERENCE_INCOMPLETE)
        else:
            highest = max((ref.reference_balance for ref in references), default=daily_reference.reference_balance)
            max_reference = max(initial_capital, highest, daily_reference.reference_balance)
    else:  # the intraday trailing maximum needs the highest intraday balance: not tracked, so not guessed
        reasons.append(MAX_METHOD_UNSUPPORTED)
    if max_reference is not None:
        max_floor = round(max_reference - max_amount, 2)

    daily_remaining = round(equity - daily_floor, 2) if daily_floor is not None else None
    max_remaining = round(equity - max_floor, 2) if max_floor is not None else None
    if daily_remaining is not None and daily_remaining <= 0:
        reasons.append(DAILY_LOSS_BREACHED)
    if max_remaining is not None and max_remaining <= 0:
        reasons.append(MAX_LOSS_BREACHED)

    breached = any(code in reasons for code in (DAILY_LOSS_BREACHED, MAX_LOSS_BREACHED))
    status: LossStatus = "breached" if breached else ("unknown" if reasons else "ok")
    return ProviderLossState(
        status=status,
        rule_set_id=rule_set.rule_set_id,
        rule_version=rule_set.version,
        timezone=daily_rule.timezone,
        initial_capital=initial_capital,
        equity=equity,
        daily_reference_balance=daily_reference_balance,
        daily_reference_at=daily_at,
        daily_loss_amount=daily_amount,
        daily_floor=daily_floor,
        daily_remaining=daily_remaining,
        max_method=max_rule.method,
        max_reference_balance=max_reference,
        max_loss_amount=max_amount,
        max_floor=max_floor,
        max_remaining=max_remaining,
        reasons=tuple(reasons),
        detail=_detail(status, reasons, daily_remaining, max_remaining),
        **accounting,
    )


def _detail(status: LossStatus, reasons: Sequence[str], daily: float | None, maximum: float | None) -> str:
    figures = ", ".join(
        f"{name} margin {value:.2f}" for name, value in (("daily", daily), ("maximum", maximum)) if value is not None
    )
    if status == "ok":
        return figures
    return f"{status}: {', '.join(reasons)}" + (f" ({figures})" if figures else "")


def remaining_percent(state: ProviderLossState, which: Literal["daily", "max"]) -> float | None:
    """The room left before the floor, as a percentage of the initial capital — the unit the Risk Engine's budgets speak."""
    remaining = state.daily_remaining if which == "daily" else state.max_remaining
    if remaining is None or state.initial_capital is None or state.initial_capital <= 0:
        return None
    return remaining / state.initial_capital * 100


def missing_days(references: Sequence[LossReference], first: date, today: date) -> list[date]:
    """The days between ``first`` and ``today`` (both included) for which no 00:00 balance is recorded."""
    have = {ref.local_date for ref in references}
    return [
        first + timedelta(days=offset)
        for offset in range((today - first).days + 1)
        if first + timedelta(days=offset) not in have
    ]


__all__ = [
    "DAILY_LOSS_BREACHED",
    "DAILY_REFERENCE_MISSING",
    "DAILY_REFERENCE_STALE",
    "EQUITY_UNKNOWN",
    "INITIAL_CAPITAL_MISSING",
    "MAX_LOSS_BREACHED",
    "MAX_METHOD_UNSUPPORTED",
    "MAX_REFERENCE_INCOMPLETE",
    "CashFlow",
    "LossReference",
    "ProviderLossState",
    "balance_at",
    "day_start_utc",
    "evaluate_loss_state",
    "local_day",
    "missing_days",
    "reference_from_flows",
    "remaining_percent",
]
