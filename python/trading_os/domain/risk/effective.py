"""The effective risk policy (ADR 0036): for every limit, **all** the values that could apply, and the one that does.

Six layers can bound a trade — the trader's own rules, the provider's, the product's, the instrument's, the market's restrictions and
the state of the account — and the strictest always prevails. The engine already takes that minimum where it decides (``risk_allowance``
for the risk of a trade, ``apply_provider_ceilings`` for the loss limits); this module does not decide anything new. It **shows its
work**: one line per limit, every candidate with where it came from, the one that binds, and whether a gate enforces it. A number that
is not enforced says so (``enforced_by = None``): showing a limit nothing applies would be a lie of its own.

A profit target is never a candidate. It is listed among the account's objectives, marked informational: a goal is not a reason to
change the risk taken, and nothing here — nor anywhere in ``domain/risk`` — reads it (a structural test keeps it so).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Literal

from trading_os.domain.market.instrument import InstrumentSpecification
from trading_os.domain.primitives import DomainModel
from trading_os.domain.providers.commission import CommissionReading
from trading_os.domain.providers.identity import AccountIdentification
from trading_os.domain.providers.rules import ProviderRuleSet
from trading_os.domain.risk.dynamic_risk import RiskAllowance
from trading_os.domain.risk.policy import RiskProfile


class LimitSource(StrEnum):
    PERSONAL = "personal"  # the trader's own rules
    PROVIDER = "provider"  # a rule common to the provider's products
    PRODUCT = "product"  # a rule of this product's contract
    INSTRUMENT = "instrument"  # what the terminal says of the symbol
    MARKET = "market"  # a restriction of the market itself (news, break)
    ACCOUNT = "account"  # the state of the account right now


# Among equal values the contract is named, not the trader's own rule: it is the commitment that cannot be changed.
_TIE_ORDER = {
    LimitSource.PRODUCT: 0,
    LimitSource.PROVIDER: 1,
    LimitSource.INSTRUMENT: 2,
    LimitSource.MARKET: 3,
    LimitSource.ACCOUNT: 4,
    LimitSource.PERSONAL: 5,
}


class LimitCandidate(DomainModel):
    source: LimitSource
    value: float
    origin: str


class EffectiveLimit(DomainModel):
    key: str
    label: str
    unit: Literal["percent", "count", "lots", "price"]
    candidates: tuple[LimitCandidate, ...]
    value: float | None  # the strictest candidate; None = nothing bounds it
    binding_source: LimitSource | None
    binding_origin: str | None
    enforced_by: str | None  # the gate or check that applies it; None = shown, not enforced
    detail: str


class PolicyRestriction(DomainModel):
    key: str
    label: str
    source: LimitSource
    active: bool
    informational: bool = False  # an objective, a documentary figure: never an input to risk
    detail: str
    origin: str | None = None


class EffectiveRiskPolicy(DomainModel):
    account_id: str | None
    product: str
    rule_set_id: str | None
    rule_version: str | None
    executable: bool
    blockers: tuple[str, ...]
    limits: tuple[EffectiveLimit, ...]
    restrictions: tuple[PolicyRestriction, ...]
    not_sourced: tuple[str, ...]
    needs_review: tuple[str, ...]
    computed_at: datetime

    def limit(self, key: str) -> EffectiveLimit | None:
        return next((item for item in self.limits if item.key == key), None)


def _strictest(candidates: Sequence[LimitCandidate]) -> LimitCandidate | None:
    return min(candidates, key=lambda item: (item.value, _TIE_ORDER[item.source])) if candidates else None


def _limit(
    key: str,
    label: str,
    unit: Literal["percent", "count", "lots", "price"],
    candidates: Sequence[LimitCandidate],
    *,
    enforced_by: str | None,
) -> EffectiveLimit:
    binding = _strictest(candidates)
    if binding is None:
        return EffectiveLimit(
            key=key,
            label=label,
            unit=unit,
            candidates=(),
            value=None,
            binding_source=None,
            binding_origin=None,
            enforced_by=enforced_by,
            detail="no limit from any source",
        )
    others = [f"{c.source.value} {c.value:g}" for c in candidates if c is not binding]
    detail = f"{binding.value:g} ({binding.source.value}: {binding.origin})" + (
        f"; also {', '.join(others)}" if others else ""
    )
    return EffectiveLimit(
        key=key,
        label=label,
        unit=unit,
        candidates=tuple(candidates),
        value=binding.value,
        binding_source=binding.source,
        binding_origin=binding.origin,
        enforced_by=enforced_by,
        detail=detail,
    )


def _origin(rule_set: ProviderRuleSet) -> str:
    return f"{rule_set.name}, rules of {rule_set.version}"


def resolve_effective_policy(
    *,
    account_id: str | None,
    personal: RiskProfile,
    rule_set: ProviderRuleSet | None,
    identification: AccountIdentification | None,
    now: datetime,
    spec: InstrumentSpecification | None = None,
    spread_cap: float | None = None,
    live_allowance: RiskAllowance | None = None,
    commission: CommissionReading | None = None,
) -> EffectiveRiskPolicy:
    """``personal`` must be the rules **before** any provider ceiling was applied to them, or the personal value shown would already be
    the provider's. Everything optional is shown only when it is known."""
    mine = "the trader's rules"
    limits: list[EffectiveLimit] = []

    def personal_candidate(value: float | None, origin: str = mine) -> list[LimitCandidate]:
        return [] if value is None else [LimitCandidate(source=LimitSource.PERSONAL, value=value, origin=origin)]

    drawdown = personal.drawdown
    daily = personal_candidate(drawdown.daily_loss_limit_percent)
    maximum = personal_candidate(drawdown.max_drawdown_limit_percent)
    if rule_set is not None and rule_set.loss_rules_sourced:
        if rule_set.daily_loss is not None:
            daily.append(
                LimitCandidate(source=LimitSource.PRODUCT, value=rule_set.daily_loss.percent, origin=_origin(rule_set))
            )
        if rule_set.max_loss is not None:
            maximum.append(
                LimitCandidate(source=LimitSource.PRODUCT, value=rule_set.max_loss.percent, origin=_origin(rule_set))
            )
    limits.append(
        _limit("daily_loss_percent", "Daily loss", "percent", daily, enforced_by="gate-daily-loss, provider loss floor")
    )
    limits.append(
        _limit(
            "weekly_loss_percent",
            "Weekly loss",
            "percent",
            personal_candidate(drawdown.weekly_loss_limit_percent),
            enforced_by="gate-weekly-loss",
        )
    )
    limits.append(
        _limit("max_loss_percent", "Maximum loss", "percent", maximum, enforced_by="gate-total-dd, provider loss floor")
    )
    limits.append(
        _limit(
            "max_trades_per_day",
            "Trades per day",
            "count",
            personal_candidate(personal.max_trades_per_day),
            enforced_by="gate-max-trades",
        )
    )
    limits.append(
        _limit(
            "max_open_positions",
            "Simultaneous positions",
            "count",
            personal_candidate(personal.positions.max_open_positions),
            enforced_by="gate-position-limit",
        )
    )

    per_trade = personal_candidate(
        min(personal.max_risk_per_trade_percent, personal.dynamic.ceiling_percent),
        "per-trade ceiling and top of the risk grid",
    )
    if live_allowance is not None and live_allowance.status == "allowed":
        per_trade.append(
            LimitCandidate(
                source=LimitSource.ACCOUNT,
                value=live_allowance.risk_percent,
                origin=f"the allowance right now, bound by {live_allowance.binding_cap}",
            )
        )
    elif live_allowance is not None:
        per_trade.append(
            LimitCandidate(
                source=LimitSource.ACCOUNT,
                value=0.0,
                origin=f"no new trade right now: {live_allowance.reason or live_allowance.status}",
            )
        )
    limits.append(
        _limit("risk_per_trade_percent", "Risk per trade", "percent", per_trade, enforced_by="risk_allowance")
    )
    limits.append(
        _limit(
            "max_open_risk_percent",
            "Open risk",
            "percent",
            personal_candidate(personal.max_open_risk_percent),
            enforced_by="gate-open-risk",
        )
    )
    limits.append(
        _limit(
            "max_correlated_risk_percent",
            "Correlated risk",
            "percent",
            personal_candidate(personal.max_correlated_risk_percent),
            enforced_by="gate-correlation",
        )
    )

    volume = personal_candidate(personal.positions.max_volume_per_order)
    if spec is not None:
        volume.append(
            LimitCandidate(source=LimitSource.INSTRUMENT, value=spec.volume_max, origin=f"{spec.name} volume maximum")
        )
        if spec.volume_limit:
            volume.append(
                LimitCandidate(
                    source=LimitSource.INSTRUMENT, value=spec.volume_limit, origin=f"{spec.name} volume limit"
                )
            )
    limits.append(_limit("volume_per_order_lots", "Volume per order", "lots", volume, enforced_by="sizing"))
    limits.append(
        _limit(
            "spread_ceiling",
            "Spread ceiling",
            "price",
            personal_candidate(spread_cap, "the trader's per-symbol ceiling"),
            enforced_by="gate-spread",
        )
    )

    request_candidates: list[LimitCandidate] = []
    if rule_set is not None and rule_set.max_requests_per_day is not None:
        request_candidates.append(
            LimitCandidate(
                source=LimitSource.PROVIDER, value=float(rule_set.max_requests_per_day), origin=_origin(rule_set)
            )
        )
    limits.append(
        _limit(
            "requests_per_day",
            "Server requests per day",
            "count",
            request_candidates,
            enforced_by="provider request budget",
        )
    )

    restrictions = _restrictions(rule_set, identification)
    if commission is not None:
        restrictions.append(
            PolicyRestriction(
                key="commission",
                label="Commission",
                source=LimitSource.ACCOUNT,
                active=True,
                informational=commission.source.value != "assumed",
                detail=f"{commission.source.value}: {commission.detail}",
            )
        )
    return EffectiveRiskPolicy(
        account_id=account_id,
        product=identification.rules_product.value if identification else "UNKNOWN",
        rule_set_id=rule_set.rule_set_id if rule_set else None,
        rule_version=rule_set.version if rule_set else None,
        executable=identification.executable if identification else False,
        blockers=tuple(blocker.value for blocker in identification.blockers)
        if identification
        else ("account_facts_missing",),
        limits=tuple(limits),
        restrictions=tuple(restrictions),
        not_sourced=rule_set.not_sourced if rule_set else (),
        needs_review=rule_set.needs_review if rule_set else (),
        computed_at=now,
    )


def _restrictions(
    rule_set: ProviderRuleSet | None, identification: AccountIdentification | None
) -> list[PolicyRestriction]:
    items: list[PolicyRestriction] = []
    if identification is not None:
        items.append(
            PolicyRestriction(
                key="identity",
                label="Account identification",
                source=LimitSource.ACCOUNT,
                active=not identification.executable,
                detail=identification.summary,
            )
        )
    if rule_set is None:
        return items
    origin = _origin(rule_set)
    items.append(
        PolicyRestriction(
            key="execution_environment",
            label="Execution environment",
            source=LimitSource.PROVIDER,
            active=rule_set.execution_environment == "simulated",
            informational=True,
            detail="simulated trading on real quotes, not a broker"
            if rule_set.execution_environment == "simulated"
            else "a broker",
            origin=origin,
        )
    )
    news = rule_set.news
    items.append(
        PolicyRestriction(
            key="news",
            label="News restriction",
            source=LimitSource.PRODUCT,
            active=news is not None,
            detail=(
                f"no order action within {news.before_seconds // 60} min before and {news.after_seconds // 60} min after a restricted release, on the instruments it touches"
                if news
                else "none on this product"
            ),
            origin=origin,
        )
    )
    overnight = rule_set.overnight
    items.append(
        PolicyRestriction(
            key="overnight",
            label="Overnight and weekend",
            source=LimitSource.PRODUCT,
            active=overnight.restricted,
            detail=(
                f"flat before any market break longer than {overnight.break_longer_than_hours:g} h"
                if overnight.restricted
                else "positions may cross a break on this product"
            ),
            origin=origin,
        )
    )
    if rule_set.daily_loss is not None and rule_set.max_loss is not None:
        items.append(
            PolicyRestriction(
                key="loss_method",
                label="How the loss floors are built",
                source=LimitSource.PRODUCT,
                active=True,
                detail=(
                    f"daily: balance at 00:00 {rule_set.daily_loss.timezone} − {rule_set.daily_loss.percent:g} % of the initial capital; "
                    f"maximum: {rule_set.max_loss.method.value}, {rule_set.max_loss.percent:g} %; equity is tested"
                ),
                origin=origin,
            )
        )
    for key, label, value in (
        ("profit_target", "Profit target", rule_set.profit_target_percent),
        ("min_trading_days", "Minimum trading days", rule_set.min_trading_days),
    ):
        if value is not None:
            items.append(
                PolicyRestriction(
                    key=key,
                    label=label,
                    source=LimitSource.PRODUCT,
                    active=False,
                    informational=True,
                    detail=f"{value:g} — an objective of the account, never a reason to raise the risk taken",
                    origin=origin,
                )
            )
    if rule_set.margin_call_percent is not None:
        items.append(
            PolicyRestriction(
                key="margin_levels",
                label="Margin call and stop out",
                source=LimitSource.PROVIDER,
                active=False,
                informational=True,
                detail=f"documentary: margin call {rule_set.margin_call_percent:g} %, stop out {rule_set.stop_out_percent or 0:g} % — the terminal states the real levels",
                origin=origin,
            )
        )
    return items


__all__ = [
    "EffectiveLimit",
    "EffectiveRiskPolicy",
    "LimitCandidate",
    "LimitSource",
    "PolicyRestriction",
    "resolve_effective_policy",
]
