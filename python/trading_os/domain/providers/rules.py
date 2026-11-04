"""What each provider's contract says, per product and per version — as **data**, with where it came from (ADR 0036).

A rule set is not a truth: it is the provider's published contract as read on a date. It carries its sources (URL, date read,
date the page says it was modified, and *how* it was read), and it says what is **not** sourced instead of guessing it. The
terminal always wins over a documentary value: a rule set bounds what the account may do, it never describes what the account is.

No ``if provider == …`` here, nor anywhere outside ``domain/accounts/profiles.py`` (architecture invariant): the behaviour of a
provider is the *content* of its rule sets, keyed by product.

The objectives of a prop phase (profit target, minimum trading days) are goals of the account, shown as such. They are never an
input to the risk taken (ADR 0036 §6): a target is not a reason to raise a risk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field

from trading_os.domain.accounts.models import FtmoChallenge, Provider
from trading_os.domain.primitives import DomainModel


class ProviderProduct(StrEnum):
    EXNESS_STANDARD = "EXNESS_STANDARD"
    FTMO_CHALLENGE_1STEP = "FTMO_CHALLENGE_1STEP"
    FTMO_CHALLENGE_2STEP = "FTMO_CHALLENGE_2STEP"
    FTMO_VERIFICATION = "FTMO_VERIFICATION"
    FTMO_ACCOUNT_1STEP = "FTMO_ACCOUNT_1STEP"
    FTMO_ACCOUNT_2STEP = "FTMO_ACCOUNT_2STEP"
    FTMO_INSTANT = "FTMO_INSTANT"
    FTMO_SWING = "FTMO_SWING"
    UNKNOWN = "UNKNOWN"


class LossMethod(StrEnum):
    STATIC_INITIAL = "static_initial"  # floor = initial capital − amount; never moves
    TRAILING_EOD_BALANCE = "trailing_eod_balance"  # floor = max(initial, highest 00:00 balance) − amount; only rises
    TRAILING_INTRADAY_BALANCE = "trailing_intraday_balance"  # as above with the intraday balance (FTMO Instant)


ReadHow = Literal["page_read", "search_summary", "user_statement"]


class RuleSource(DomainModel):
    """Where a rule came from. ``read_how`` is the honest part: a page we read, a search summary of a page we could not read,
    or a figure the user gave us."""

    url: str
    retrieved_on: date
    page_modified_on: date | None = None
    read_how: ReadHow = "page_read"
    note: str = ""


class DailyLossRule(DomainModel):
    percent: float = Field(gt=0)  # of the initial capital
    timezone: str  # IANA zone in which the day starts — named, never deduced from the broker's clock
    reference: Literal["balance"] = "balance"  # the balance recorded at the day's start
    tested_on: Literal["equity"] = "equity"  # balance + floating P/L ± swaps − commissions


class MaxLossRule(DomainModel):
    percent: float = Field(gt=0)  # of the initial capital
    method: LossMethod
    timezone: str  # the zone in which a day's closing balance is recorded (00:00 of the next day)
    tested_on: Literal["equity"] = "equity"


NewsAction = Literal["open", "close", "modify", "pending", "stop_loss", "take_profit"]


class NewsRestrictionRule(DomainModel):
    before_seconds: int = Field(ge=0)
    after_seconds: int = Field(ge=0)
    actions: tuple[NewsAction, ...]
    # Currency (or asset) → what it restricts. ``forex`` = every forex pair containing the currency; ``symbols`` = canonical names.
    forex_currencies: tuple[str, ...]
    symbols_by_currency: Mapping[str, tuple[str, ...]]


class OvernightRule(DomainModel):
    """Whether a position may cross a market break. ``break_longer_than_hours`` is the length from which a break counts."""

    restricted: bool
    break_longer_than_hours: float | None = None


class ProviderRuleSet(DomainModel):
    rule_set_id: str  # ``<product>@<version>``
    product: ProviderProduct
    provider: Provider
    version: str  # ISO date: when the provider's page was last modified, as far as we know
    effective_from: date
    name: str
    execution_environment: Literal["broker", "simulated"]  # FTMO is simulated trading on real quotes, never a broker
    daily_loss: DailyLossRule | None = None
    max_loss: MaxLossRule | None = None
    profit_target_percent: float | None = None  # an objective of the account, never an input to risk
    min_trading_days: int | None = None
    news: NewsRestrictionRule | None = None
    overnight: OvernightRule = OvernightRule(restricted=False)
    max_requests_per_day: int | None = None
    max_leverage: int | None = None  # documentary: the terminal states the real leverage
    # What the contract states the commission is, per lot round trip. ``None`` = it does not state one (FTMO publishes it per symbol).
    # Documentary: the account's own deals prevail the day they show a charge (``providers/commission.py``).
    documentary_commission_per_lot: float | None = None
    margin_call_percent: float | None = None  # documentary (Exness): the terminal states the real levels
    stop_out_percent: float | None = None
    # False = the provider's loss limits for this product are not sourced: the account cannot trade under them.
    loss_rules_sourced: bool
    not_sourced: tuple[str, ...] = ()
    needs_review: tuple[str, ...] = ()
    sources: tuple[RuleSource, ...] = ()

    @property
    def requires_loss_references(self) -> bool:
        return self.daily_loss is not None or self.max_loss is not None


_READ = date(2026, 11, 3)
_PRAGUE = "Europe/Prague"  # CE(S)T

_OBJECTIVES = RuleSource(
    url="https://ftmo.com/en/trading-objectives/",
    retrieved_on=_READ,
    page_modified_on=date(2026, 11, 2),
    note="lu par extraction automatique du texte de la page ; à relire par Exhorte avant tout compte réel",
)
_NEWS = RuleSource(
    url="https://ftmo.com/faq/can-i-trade-news/",
    retrieved_on=_READ,
    page_modified_on=date(2026, 10, 11),
    note="lu par extraction automatique du texte de la page",
)
_OVERNIGHT = RuleSource(
    url="https://ftmo.com/en/faq/can-i-hold-positions-overnight-or-over-the-weekend/",
    retrieved_on=_READ,
    page_modified_on=date(2026, 10, 11),
    note="lu par extraction automatique du texte de la page",
)
_SPECS = RuleSource(
    url="https://ftmo.com/en/faq/what-are-the-account-specifications/",
    retrieved_on=_READ,
    page_modified_on=date(2026, 10, 5),
    note="effet de levier 1:100 (Standard) et 1:30 (Swing) ; commission non indiquée ; serveur MT en GMT+2 avec heure d'été",
)
_FORBIDDEN = RuleSource(
    url="https://ftmo.com/en/forbidden-trading-practices/",
    retrieved_on=_READ,
    page_modified_on=date(2026, 11, 2),
    note="plus de 2 000 requêtes de serveur par jour = hyperactivité d'un EA",
)
_EXNESS_STANDARD = RuleSource(
    url="https://get.exness.help/hc/en-us/articles/17537782738460-Standard-account",
    retrieved_on=_READ,
    read_how="search_summary",
    note="page illisible (HTTP 403 le 2026-11-03) ; valeurs données par Exhorte dans la mission du 2026-11-03 et recoupées par un résumé de recherche web",
)

_FTMO_NEWS_RULE = NewsRestrictionRule(
    before_seconds=120,
    after_seconds=120,
    actions=("open", "close", "modify", "pending", "stop_loss", "take_profit"),
    forex_currencies=("USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF"),
    symbols_by_currency={
        "USD": ("XAUUSD", "US2000", "US500", "US100", "US30", "DXY"),
        "OIL": ("USOIL", "UKOIL"),
    },
)
_NO_NEWS_IN_EVALUATION = "aucune restriction de news pendant Challenge et Verification (page FAQ news, 2026-10-11)"


def _ftmo(
    product: ProviderProduct,
    name: str,
    *,
    daily: float,
    max_loss: float,
    method: LossMethod,
    target: float | None = None,
    min_days: int | None = None,
    news: bool,
    overnight: bool,
    needs_review: tuple[str, ...] = (),
) -> ProviderRuleSet:
    version = "2026-11-02"
    return ProviderRuleSet(
        rule_set_id=f"{product.value}@{version}",
        product=product,
        provider=Provider.FTMO,
        version=version,
        effective_from=date(2026, 11, 2),
        name=name,
        execution_environment="simulated",
        daily_loss=DailyLossRule(percent=daily, timezone=_PRAGUE),
        max_loss=MaxLossRule(percent=max_loss, method=method, timezone=_PRAGUE),
        profit_target_percent=target,
        min_trading_days=min_days,
        news=_FTMO_NEWS_RULE if news else None,
        overnight=OvernightRule(restricted=overnight, break_longer_than_hours=2.0 if overnight else None),
        max_requests_per_day=2_000,
        max_leverage=100,
        loss_rules_sourced=True,
        not_sourced=(
            "commission par symbole (publiée sur le site et la plateforme, non lue)",
            "sessions de négociation",
        ),
        needs_review=needs_review,
        sources=(_OBJECTIVES, _NEWS, _OVERNIGHT, _SPECS, _FORBIDDEN),
    )


_TRAILING_AMOUNT = (
    "le montant de la perte maximale glissante est lu comme un pourcentage du capital initial ; la page ne le dit pas "
    "en toutes lettres"
)

RULE_SETS: tuple[ProviderRuleSet, ...] = (
    _ftmo(
        ProviderProduct.FTMO_CHALLENGE_1STEP,
        "FTMO Challenge 1-Step",
        daily=3.0,
        max_loss=10.0,
        method=LossMethod.TRAILING_EOD_BALANCE,
        target=10.0,
        news=False,
        overnight=False,
        needs_review=(_TRAILING_AMOUNT, _NO_NEWS_IN_EVALUATION),
    ),
    _ftmo(
        ProviderProduct.FTMO_CHALLENGE_2STEP,
        "FTMO Challenge 2-Step",
        daily=5.0,
        max_loss=10.0,
        method=LossMethod.STATIC_INITIAL,
        target=10.0,
        min_days=4,
        news=False,
        overnight=False,
        needs_review=(_NO_NEWS_IN_EVALUATION,),
    ),
    _ftmo(
        ProviderProduct.FTMO_VERIFICATION,
        "FTMO Verification (2-Step)",
        daily=5.0,
        max_loss=10.0,
        method=LossMethod.STATIC_INITIAL,
        target=5.0,
        min_days=4,
        news=False,
        overnight=False,
        needs_review=(_NO_NEWS_IN_EVALUATION,),
    ),
    _ftmo(
        ProviderProduct.FTMO_ACCOUNT_1STEP,
        "FTMO Account 1-Step",
        daily=3.0,
        max_loss=10.0,
        method=LossMethod.TRAILING_EOD_BALANCE,
        news=True,
        overnight=True,
        needs_review=(_TRAILING_AMOUNT,),
    ),
    _ftmo(
        ProviderProduct.FTMO_ACCOUNT_2STEP,
        "FTMO Account 2-Step",
        daily=5.0,
        max_loss=10.0,
        method=LossMethod.STATIC_INITIAL,
        news=True,
        overnight=True,
    ),
    _ftmo(
        ProviderProduct.FTMO_INSTANT,
        "FTMO Instant",
        daily=3.0,
        max_loss=10.0,
        method=LossMethod.TRAILING_INTRADAY_BALANCE,
        news=True,
        overnight=True,
        needs_review=(
            "la perte maximale glissante d'Instant est décrite en une ligne (« fondée sur le solde intrajournalier ») : "
            "la méthode exacte est à relire sur la page avant tout usage",
        ),
    ),
    ProviderRuleSet(
        rule_set_id="FTMO_SWING@2026-11-02",
        product=ProviderProduct.FTMO_SWING,
        provider=Provider.FTMO,
        version="2026-11-02",
        effective_from=date(2026, 11, 2),
        name="FTMO Swing",
        execution_environment="simulated",
        news=None,  # exempt (FAQ news)
        overnight=OvernightRule(restricted=False),  # exempt (FAQ overnight)
        max_requests_per_day=2_000,
        max_leverage=30,
        loss_rules_sourced=False,
        not_sourced=(
            "limites de perte quotidienne et maximale du produit Swing (non lues sur les pages consultées)",
            "commission par symbole",
            "sessions de négociation",
        ),
        sources=(_NEWS, _OVERNIGHT, _SPECS, _FORBIDDEN),
    ),
    ProviderRuleSet(
        rule_set_id="EXNESS_STANDARD@2026-11-03",
        product=ProviderProduct.EXNESS_STANDARD,
        provider=Provider.EXNESS,
        version="2026-11-03",
        effective_from=date(2026, 11, 3),
        name="Exness Standard (MT5)",
        execution_environment="broker",
        margin_call_percent=60.0,
        stop_out_percent=0.0,
        documentary_commission_per_lot=0.0,  # « aucune commission de trading sur Standard »
        # Exness imposes no loss limit: the personal rules are the only ones. Nothing contractual is missing.
        loss_rules_sourced=True,
        not_sourced=(
            "swap par instrument (publié par le courtier, lu sur le terminal)",
            "commission : aucune annoncée sur Standard, valeur documentaire ; la mesure vient des deals du compte",
            "horaires par instrument",
        ),
        sources=(_EXNESS_STANDARD,),
    ),
)

_BY_ID: Mapping[str, ProviderRuleSet] = {rule_set.rule_set_id: rule_set for rule_set in RULE_SETS}


def rule_set_for(product: ProviderProduct, on: date | None = None) -> ProviderRuleSet | None:
    """The rule set of ``product`` in force on ``on`` (the latest version that began by then); ``None`` for an unknown product."""
    candidates = [
        rule_set
        for rule_set in RULE_SETS
        if rule_set.product is product and (on is None or rule_set.effective_from <= on)
    ]
    return max(candidates, key=lambda rule_set: rule_set.effective_from) if candidates else None


def rule_set_by_id(rule_set_id: str) -> ProviderRuleSet | None:
    return _BY_ID.get(rule_set_id)


def ftmo_product_of(challenge: FtmoChallenge | None) -> ProviderProduct:
    """The FTMO product a declared challenge describes. A challenge nobody declared is ``UNKNOWN`` — never a default 2-Step."""
    if challenge is None:
        return ProviderProduct.UNKNOWN
    if challenge.variant == "swing":
        return ProviderProduct.FTMO_SWING
    if challenge.type == "instant":
        return ProviderProduct.FTMO_INSTANT
    return _FTMO_BY_SHAPE.get((challenge.type, challenge.phase), ProviderProduct.UNKNOWN)


_FTMO_BY_SHAPE: Mapping[tuple[str, str], ProviderProduct] = {
    ("1-step", "challenge"): ProviderProduct.FTMO_CHALLENGE_1STEP,
    ("2-step", "challenge"): ProviderProduct.FTMO_CHALLENGE_2STEP,
    ("2-step", "verification"): ProviderProduct.FTMO_VERIFICATION,
    ("1-step", "funded"): ProviderProduct.FTMO_ACCOUNT_1STEP,
    ("2-step", "funded"): ProviderProduct.FTMO_ACCOUNT_2STEP,
}  # a 1-Step has no verification phase: that shape is UNKNOWN, not guessed


def products_of(provider: Provider) -> Sequence[ProviderProduct]:
    return [rule_set.product for rule_set in RULE_SETS if rule_set.provider is provider]


__all__ = [
    "RULE_SETS",
    "DailyLossRule",
    "LossMethod",
    "MaxLossRule",
    "NewsRestrictionRule",
    "OvernightRule",
    "ProviderProduct",
    "ProviderRuleSet",
    "RuleSource",
    "ftmo_product_of",
    "products_of",
    "rule_set_by_id",
    "rule_set_for",
]
