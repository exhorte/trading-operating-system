"""Who is this account? (ADR 0036) — decided from several **independent** facts the terminal reports, never from the login alone and
never from what the user says alone.

Signals, each its own line in the answer:

* the server name, the company of the account, the company of the terminal — three independent readings of the provider;
* the suffix the terminal's symbols really carry (Exness Standard: ``…m``) — a weak signal for the product, never for the provider;
* the leverage (FTMO Swing is 1:30, Standard up to 1:100) — a cross-check, never a proof;
* what the user declared (provider, environment, challenge) — confirms or contradicts, never suffices.

The answer says how sure it is and **why not**, in stable codes. A provider that cannot be told apart, two providers at once, a
declaration the terminal contradicts, a product nobody declared, a contract not sourced: each makes the account *not executable*
(``executable = False``). Not executable means the Risk Engine refuses every new entry and says why; reading and monitoring go on.

The provider-specific part (which names mean which provider, which suffix means which product) is data in
``domain/accounts/profiles.py``; this module is the same for every provider.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from trading_os.domain.accounts.models import AccountType, Environment, FtmoChallenge, Provider
from trading_os.domain.accounts.profiles import PROFILES, ProductEvidence, provider_signatures
from trading_os.domain.primitives import DomainModel
from trading_os.domain.providers.rules import ProviderProduct, ftmo_product_of, rule_set_for

AccountMode = Literal["DEMO", "REAL", "SIMULATED"]
TradeMode = Literal["demo", "contest", "real", "unknown"]


class Confidence(StrEnum):
    CONFIRMED = "CONFIRMED"  # the terminal's facts agree with each other and with the user's declaration
    PROBABLE = "PROBABLE"  # the facts agree; nothing contradicts; the declaration is absent or thinner
    WEAK = "WEAK"  # one reading only
    CONFLICT = "CONFLICT"  # two readings disagree
    NONE = "NONE"  # nothing identifies it


class IdentityBlocker(StrEnum):
    FACTS_MISSING = "account_facts_missing"
    PROVIDER_NOT_IDENTIFIED = "provider_not_identified"
    PROVIDER_AMBIGUOUS = "provider_ambiguous"
    PROVIDER_MISMATCH = "provider_mismatch"  # the user declared one provider, the terminal says another
    ENVIRONMENT_MISMATCH = "environment_mismatch"  # declared demo on a real terminal (or the reverse)
    PRODUCT_UNKNOWN = "account_product_unknown"
    RULES_UNSOURCED = "provider_rules_unsourced"
    RULES_ON_REAL_ACCOUNT = "rules_profile_on_real_account"  # another provider's contract rehearsed on real money
    LEVERAGE_CONTRADICTS = (
        "leverage_contradicts_product"  # the terminal's leverage is one the declared product cannot have
    )


class SignalKind(StrEnum):
    SERVER = "server"
    COMPANY = "company"
    TERMINAL_COMPANY = "terminal_company"
    SYMBOL_SUFFIX = "symbol_suffix"
    LEVERAGE = "leverage"
    TRADE_MODE = "trade_mode"
    DECLARED_PROVIDER = "declared_provider"
    DECLARED_ENVIRONMENT = "declared_environment"
    DECLARED_PRODUCT = "declared_product"


class IdentitySignal(DomainModel):
    kind: SignalKind
    value: str
    points_to: str | None  # a provider or a product code; ``None`` = it points to nothing we know
    observed: bool  # read from the terminal (True) or declared by the user (False)


class IdentityFacts(DomainModel):
    """Everything identification reads. ``None`` = the terminal did not say (never an invented value)."""

    login: int | None = None
    server: str | None = None
    company: str | None = None
    terminal_company: str | None = None
    trade_mode: TradeMode | None = None
    currency: str | None = None
    leverage: int | None = None
    observed_suffixes: tuple[str, ...] = ()
    declared_provider: Provider | None = None
    declared_environment: Environment | None = None
    declared_account_type: AccountType | None = None
    challenge: FtmoChallenge | None = None  # the contract the user declared the account follows
    observed_at: datetime | None = None


class AccountIdentification(DomainModel):
    provider: Provider | None  # who carries the account (the terminal's word)
    provider_confidence: Confidence
    broker_product: ProviderProduct  # the product of the carrier: Exness Standard…
    rules_product: ProviderProduct  # the contract whose rules apply: the carrier's, or a declared rehearsal's
    rules_rehearsal: bool  # the rules are another provider's contract, rehearsed on this account
    product_confidence: Confidence
    rule_set_id: str | None
    account_mode: AccountMode | None
    signals: tuple[IdentitySignal, ...]
    conflicts: tuple[str, ...]
    blockers: tuple[IdentityBlocker, ...]
    executable: bool
    needs_confirmation: bool  # the user is asked to declare something before the account may trade
    summary: str


_BLOCKER_TEXT: dict[IdentityBlocker, str] = {
    IdentityBlocker.FACTS_MISSING: "the terminal gave no account facts: server, company, leverage or currency is missing",
    IdentityBlocker.PROVIDER_NOT_IDENTIFIED: "the provider cannot be told from the terminal's names",
    IdentityBlocker.PROVIDER_AMBIGUOUS: "the terminal's names point to more than one provider",
    IdentityBlocker.PROVIDER_MISMATCH: "the declared provider is not the one the terminal reports",
    IdentityBlocker.ENVIRONMENT_MISMATCH: "the declared environment (demo or real) is not the terminal's",
    IdentityBlocker.PRODUCT_UNKNOWN: "the account's product is not identified: declare it before this account may trade",
    IdentityBlocker.RULES_UNSOURCED: "the provider's loss rules for this product are not sourced",
    IdentityBlocker.RULES_ON_REAL_ACCOUNT: "another provider's rules can be rehearsed on a demo account only",
    IdentityBlocker.LEVERAGE_CONTRADICTS: "the terminal's leverage is above what the declared product allows",
}


def blocker_text(blocker: IdentityBlocker) -> str:
    return _BLOCKER_TEXT[blocker]


def _matches(text: str | None, pattern: re.Pattern[str]) -> bool:
    return bool(text) and pattern.search(text or "") is not None


def _provider_signals(facts: IdentityFacts) -> tuple[list[IdentitySignal], dict[Provider, int], int]:
    """Each reading of the provider, how many independent readings support each provider, and how many name nobody we know."""
    readings = (
        (SignalKind.SERVER, facts.server),
        (SignalKind.COMPANY, facts.company),
        (SignalKind.TERMINAL_COMPANY, facts.terminal_company),
    )
    signals: list[IdentitySignal] = []
    support: dict[Provider, int] = {}
    unmatched = 0
    for kind, text in readings:
        if not text:
            continue
        owners = [
            provider
            for provider, signature in provider_signatures()
            if _matches(text, signature.server if kind is SignalKind.SERVER else signature.company)
        ]
        points_to = owners[0].value if len(owners) == 1 else None
        unmatched += not owners
        signals.append(IdentitySignal(kind=kind, value=text, points_to=points_to, observed=True))
        for owner in owners:
            support[owner] = support.get(owner, 0) + 1
    return signals, support, unmatched


def _account_mode(provider: Provider | None, trade_mode: TradeMode | None) -> AccountMode | None:
    if provider is None:
        return None
    if PROFILES[provider].signature.execution_environment == "simulated":
        return "SIMULATED"
    if trade_mode in ("demo", "contest"):
        return "DEMO"
    return "REAL" if trade_mode == "real" else None


def identify_account(facts: IdentityFacts) -> AccountIdentification:
    signals, support, unmatched = _provider_signals(facts)
    conflicts: list[str] = []
    blockers: list[IdentityBlocker] = []

    missing = [name for name, value in (("server", facts.server), ("company", facts.company)) if not value]
    if facts.leverage is None or facts.currency is None:
        missing += [
            name for name, value in (("leverage", facts.leverage), ("currency", facts.currency)) if value is None
        ]
    if missing:
        blockers.append(IdentityBlocker.FACTS_MISSING)
        conflicts.append(f"missing from the terminal: {', '.join(missing)}")

    # --- the provider
    provider: Provider | None = None
    confidence = Confidence.NONE
    if len(support) > 1:
        blockers.append(IdentityBlocker.PROVIDER_AMBIGUOUS)
        confidence = Confidence.CONFLICT
        conflicts.append("the names point to " + " and ".join(sorted(p.value for p in support)))
    elif len(support) == 1:
        provider, readings = next(iter(support.items()))
        declared_agrees = facts.declared_provider is provider
        if facts.declared_provider is not None:
            signals.append(
                IdentitySignal(
                    kind=SignalKind.DECLARED_PROVIDER,
                    value=facts.declared_provider.value,
                    points_to=facts.declared_provider.value,
                    observed=False,
                )
            )
        if facts.declared_provider is not None and not declared_agrees:
            blockers.append(IdentityBlocker.PROVIDER_MISMATCH)
            confidence = Confidence.CONFLICT
            conflicts.append(f"declared {facts.declared_provider.value}, the terminal reports {provider.value}")
        elif readings >= 2:
            confidence = Confidence.CONFIRMED if declared_agrees else Confidence.PROBABLE
        else:
            # One reading of the terminal: it is enough only when the user's declaration says the same thing.
            confidence = Confidence.PROBABLE if declared_agrees else Confidence.WEAK
        if (
            unmatched > readings
        ):  # most of what the terminal says names nobody we know: the one match is not the account
            confidence = Confidence.WEAK
            conflicts.append(f"{unmatched} of {unmatched + readings} readings name no provider we know")
    if confidence is Confidence.NONE and provider is None:
        blockers.append(IdentityBlocker.PROVIDER_NOT_IDENTIFIED)
    elif confidence is Confidence.WEAK:
        blockers.append(IdentityBlocker.PROVIDER_NOT_IDENTIFIED)  # one unconfirmed reading is not enough to trade on

    # --- the environment: a declared demo on a real terminal is the one mistake that must never pass
    mode = _account_mode(provider, facts.trade_mode)
    if facts.trade_mode is not None:
        signals.append(
            IdentitySignal(kind=SignalKind.TRADE_MODE, value=facts.trade_mode, points_to=None, observed=True)
        )
    if facts.declared_environment is not None:
        signals.append(
            IdentitySignal(
                kind=SignalKind.DECLARED_ENVIRONMENT,
                value=facts.declared_environment.value,
                points_to=None,
                observed=False,
            )
        )
    if (
        provider is not None
        and PROFILES[provider].signature.execution_environment == "broker"
        and mode is not None
        and facts.declared_environment is not None
        and (facts.declared_environment is Environment.LIVE) != (mode == "REAL")
    ):
        blockers.append(IdentityBlocker.ENVIRONMENT_MISMATCH)
        conflicts.append(f"declared {facts.declared_environment.value}, the terminal says {facts.trade_mode}")

    # --- the product, and the contract whose rules apply
    broker_product = ProviderProduct.UNKNOWN
    product_confidence = Confidence.NONE
    if provider is not None:
        evidence = ProductEvidence(observed_suffixes=facts.observed_suffixes, challenge=facts.challenge)
        broker_product = PROFILES[provider].resolve_product(evidence)
        for suffix in facts.observed_suffixes:
            signals.append(
                IdentitySignal(kind=SignalKind.SYMBOL_SUFFIX, value=suffix or "(none)", points_to=None, observed=True)
            )
        if broker_product is not ProviderProduct.UNKNOWN:
            declared = (
                facts.challenge is not None
                and PROFILES[provider].resolve_product(ProductEvidence(challenge=facts.challenge))
                is not ProviderProduct.UNKNOWN
            )
            product_confidence = Confidence.CONFIRMED if declared else Confidence.PROBABLE
            if declared:
                signals.append(
                    IdentitySignal(
                        kind=SignalKind.DECLARED_PRODUCT,
                        value=broker_product.value,
                        points_to=broker_product.value,
                        observed=False,
                    )
                )

    rules_product = broker_product
    rehearsal = False
    if facts.challenge is not None:
        declared_contract = ftmo_product_of(facts.challenge)
        if declared_contract is not ProviderProduct.UNKNOWN and (
            provider is None or _provider_of(declared_contract) is not provider
        ):
            rules_product, rehearsal = declared_contract, provider is not None
            product_confidence = Confidence.CONFIRMED
            signals.append(
                IdentitySignal(
                    kind=SignalKind.DECLARED_PRODUCT,
                    value=declared_contract.value,
                    points_to=declared_contract.value,
                    observed=False,
                )
            )
    if rehearsal and mode == "REAL":
        blockers.append(IdentityBlocker.RULES_ON_REAL_ACCOUNT)
    if rules_product is ProviderProduct.UNKNOWN:
        blockers.append(IdentityBlocker.PRODUCT_UNKNOWN)

    rule_set = rule_set_for(rules_product) if rules_product is not ProviderProduct.UNKNOWN else None
    if rule_set is not None and not rule_set.loss_rules_sourced:
        blockers.append(IdentityBlocker.RULES_UNSOURCED)

    leverage_note = _leverage_conflict(facts, rules_product)
    if leverage_note:
        conflicts.append(leverage_note)
        if not rehearsal:  # a rehearsal follows another contract on another broker's leverage: informative only
            blockers.append(IdentityBlocker.LEVERAGE_CONTRADICTS)
    if facts.leverage is not None:
        signals.append(
            IdentitySignal(kind=SignalKind.LEVERAGE, value=str(facts.leverage), points_to=None, observed=True)
        )

    unique = tuple(dict.fromkeys(blockers))
    needs_confirmation = bool(
        {IdentityBlocker.PRODUCT_UNKNOWN, IdentityBlocker.PROVIDER_MISMATCH, IdentityBlocker.ENVIRONMENT_MISMATCH}
        & set(unique)
    )
    return AccountIdentification(
        provider=provider,
        provider_confidence=confidence,
        broker_product=broker_product,
        rules_product=rules_product,
        rules_rehearsal=rehearsal,
        product_confidence=product_confidence,
        rule_set_id=rule_set.rule_set_id if rule_set else None,
        account_mode=mode,
        signals=tuple(signals),
        conflicts=tuple(conflicts),
        blockers=unique,
        executable=not unique,
        needs_confirmation=needs_confirmation,
        summary=_summary(provider, confidence, rules_product, unique),
    )


def _provider_of(product: ProviderProduct) -> Provider | None:
    rule_set = rule_set_for(product)
    return rule_set.provider if rule_set else None


def _leverage_conflict(facts: IdentityFacts, product: ProviderProduct) -> str | None:
    """FTMO Swing is capped at 1:30 and Standard at 1:100 (page « account specifications », 2026-10-05): a leverage the product
    cannot have contradicts the declaration. Information only — a lower leverage is not a proof of anything."""
    rule_set = rule_set_for(product)
    if facts.leverage is None or rule_set is None or rule_set.max_leverage is None:
        return None
    if facts.leverage > rule_set.max_leverage:
        return f"leverage 1:{facts.leverage} is above the 1:{rule_set.max_leverage} the product allows"
    return None


def _summary(
    provider: Provider | None, confidence: Confidence, product: ProviderProduct, blockers: tuple[IdentityBlocker, ...]
) -> str:
    who = provider.value if provider is not None else "unidentified provider"
    if not blockers:
        return f"{who} ({confidence.value.lower()}), product {product.value}: executable"
    return f"{who} ({confidence.value.lower()}), product {product.value}: not executable — " + "; ".join(
        blocker_text(blocker) for blocker in blockers
    )
