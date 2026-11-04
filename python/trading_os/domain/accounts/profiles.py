"""Provider profiles: what makes an FTMO account and an Exness account behave differently — **without a single**
``if provider == …`` anywhere else. A registry maps each provider to the factory of its default rules.

Only facts that were sourced are encoded. FTMO's 2-Step *Challenge* phase comes from the trader's own MetriX exports
(4 minimum trading days, 10 % profit target, −5 % daily and −10 % overall of the initial size); verification, funded
and 1-step were never shown in those exports and stay ``None`` — « non sourcé », not guessed (TODO(FTMO-rules)).
The discipline limits (risk per trade, trades per day…) are the trader's own and identical across providers; the
numbers the user fixed on 2026-09-26 are theirs to write into the account rules, not defaults baked into code.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from trading_os.domain.accounts.models import (
    AccountRules,
    AccountType,
    ExecutionLimits,
    ExecutionProfile,
    FtmoChallenge,
    Provider,
    TradingRules,
)
from trading_os.domain.primitives import DomainModel
from trading_os.domain.providers.rules import ProviderProduct, ftmo_product_of, rule_set_for
from trading_os.domain.risk.policy import DrawdownPolicy, RiskProfile
from trading_os.shared.errors import ValidationFailed


class ProfileParams(DomainModel):
    account_type: AccountType
    reference_balance: float | None = None  # direct accounts: the capital the trader commits
    challenge: FtmoChallenge | None = None  # prop accounts


class ProductEvidence(DomainModel):
    """What can tell a provider's products apart: the suffixes the terminal's symbols really carry, and what the user declared."""

    observed_suffixes: tuple[str, ...] = ()
    challenge: FtmoChallenge | None = None


@dataclass(frozen=True)
class ProviderSignature:
    """How a provider shows itself to the terminal (ADR 0036). Each pattern is one **independent** signal: the server name, the
    company the account reports, the company the terminal reports. ``execution_environment`` says what kind of place it is — FTMO
    is simulated trading on real quotes, never a broker."""

    server: re.Pattern[str]
    company: re.Pattern[str]
    execution_environment: Literal["broker", "simulated"]
    typical_suffix: str  # a weak signal only: never enough on its own


def _exness_product(evidence: ProductEvidence) -> ProviderProduct:
    """Standard accounts name their symbols with a trailing ``m``; Raw, Zero and Pro do not. One observed suffix, all alike."""
    return ProviderProduct.EXNESS_STANDARD if evidence.observed_suffixes == ("m",) else ProviderProduct.UNKNOWN


def _ftmo_product_resolver(evidence: ProductEvidence) -> ProviderProduct:
    """FTMO's product is not readable from the terminal: it is what the user declared, or it is unknown — never a default."""
    return ftmo_product_of(evidence.challenge)


@dataclass(frozen=True)
class ProviderProfile:
    provider: Provider
    symbol_suffix: str
    allowed_account_types: frozenset[AccountType]
    build_rules: Callable[[ProfileParams], AccountRules]
    signature: ProviderSignature
    resolve_product: Callable[[ProductEvidence], ProviderProduct]


_PHASE_BY_TYPE = {
    AccountType.PROP_CHALLENGE: "challenge",
    AccountType.PROP_VERIFICATION: "verification",
    AccountType.PROP_FUNDED: "funded",
}


def _ftmo_objectives(challenge: FtmoChallenge) -> tuple[int | None, float | None]:
    if challenge.type == "2-step" and challenge.phase == "challenge":
        return 4, 10.0  # sourced: FTMO MetriX « Objectifs » of a 2-Step challenge
    return None, None  # TODO(FTMO-rules): verification, funded and 1-step are not in the exports


def _build_ftmo(params: ProfileParams) -> AccountRules:
    phase = _PHASE_BY_TYPE[params.account_type]
    challenge = params.challenge
    if challenge is not None and challenge.phase != phase:
        raise ValidationFailed(
            f"challenge phase {challenge.phase!r} does not match the account type {params.account_type}",
            code="phase_mismatch",
        )
    # No challenge declared = no product: nothing is invented (ADR 0036 — a default 2-Step of 10 000 was attributed here before).
    # The account is then not executable until the user declares its product; the reference is only what was given.
    reference = challenge.account_size if challenge is not None else params.reference_balance
    min_days, target = _ftmo_objectives(challenge) if challenge is not None else (None, None)
    return AccountRules(
        risk_profile=RiskProfile(
            drawdown=DrawdownPolicy(
                daily_loss_limit_percent=5.0, max_drawdown_limit_percent=10.0, reference_balance=reference
            ),
        ),
        trading_rules=TradingRules(challenge=challenge, min_trading_days=min_days, profit_target_percent=target),
        execution_profile=ExecutionProfile(
            limits=ExecutionLimits(commission_per_lot_round_trip=5.0)  # ≈ 5 $/lot round trip (fiche S01)
        ),
    )


def _build_exness(params: ProfileParams) -> AccountRules:
    return AccountRules(
        risk_profile=RiskProfile(
            drawdown=DrawdownPolicy(
                daily_loss_limit_percent=5.0,
                max_drawdown_limit_percent=10.0,
                reference_balance=params.reference_balance,
            ),
        ),
        trading_rules=TradingRules(),
        # 0 matches the Standard account measured in Phase 0 (`*m` symbols); it is not a claim about Raw or Pro.
        execution_profile=ExecutionProfile(limits=ExecutionLimits(commission_per_lot_round_trip=0.0)),
    )


PROFILES: Mapping[Provider, ProviderProfile] = {
    Provider.EXNESS: ProviderProfile(
        provider=Provider.EXNESS,
        symbol_suffix="m",
        allowed_account_types=frozenset({AccountType.DIRECT}),
        build_rules=_build_exness,
        signature=ProviderSignature(
            server=re.compile(r"^exness", re.IGNORECASE),
            company=re.compile(r"exness", re.IGNORECASE),
            execution_environment="broker",
            typical_suffix="m",
        ),
        resolve_product=_exness_product,
    ),
    Provider.FTMO: ProviderProfile(
        provider=Provider.FTMO,
        symbol_suffix="",
        allowed_account_types=frozenset(
            {AccountType.PROP_CHALLENGE, AccountType.PROP_VERIFICATION, AccountType.PROP_FUNDED}
        ),
        build_rules=_build_ftmo,
        signature=ProviderSignature(
            server=re.compile(r"^ftmo", re.IGNORECASE),
            company=re.compile(r"ftmo", re.IGNORECASE),
            execution_environment="simulated",
            typical_suffix="",
        ),
        resolve_product=_ftmo_product_resolver,
    ),
}


def provider_signatures() -> Sequence[tuple[Provider, ProviderSignature]]:
    return [(provider, profile.signature) for provider, profile in PROFILES.items()]


class ProviderCeilings(DomainModel):
    """What the provider's own contract forbids exceeding (ADR 0019): ``None`` = no sourced ceiling, never a guess.
    An internal limit is a promise to oneself; it is never a licence to go past this — the strictest always wins."""

    daily_loss_percent: float | None = None
    max_drawdown_percent: float | None = None


def provider_ceilings(challenge: FtmoChallenge | None) -> ProviderCeilings:
    """The ceilings of the contract the rules describe, read from the sourced rule set of its product (ADR 0036). A FTMO challenge
    *in the rules* is the FTMO contract, whichever broker carries the account: that is what lets a demo account at another broker
    rehearse the FTMO profile (ADR 0020). A product whose loss rules are not sourced (Swing) or not declared has **no** ceiling here
    — it is refused as a product by the identity gate, never trusted at an invented percentage."""
    rule_set = rule_set_for(ftmo_product_of(challenge))
    if rule_set is None or not rule_set.loss_rules_sourced or rule_set.daily_loss is None or rule_set.max_loss is None:
        return ProviderCeilings()
    return ProviderCeilings(
        daily_loss_percent=rule_set.daily_loss.percent, max_drawdown_percent=rule_set.max_loss.percent
    )


def apply_provider_ceilings(rules: AccountRules, ceilings: ProviderCeilings) -> AccountRules:
    """The rules with every loss limit brought under the provider's ceiling. Same object when nothing changes."""
    drawdown = rules.risk_profile.drawdown
    daily, total = drawdown.daily_loss_limit_percent, drawdown.max_drawdown_limit_percent
    if ceilings.daily_loss_percent is not None:
        daily = min(daily, ceilings.daily_loss_percent)
    if ceilings.max_drawdown_percent is not None:
        total = min(total, ceilings.max_drawdown_percent)
    if (daily, total) == (drawdown.daily_loss_limit_percent, drawdown.max_drawdown_limit_percent):
        return rules
    clamped = drawdown.model_copy(update={"daily_loss_limit_percent": daily, "max_drawdown_limit_percent": total})
    return rules.model_copy(update={"risk_profile": rules.risk_profile.model_copy(update={"drawdown": clamped})})


def provider_profile(provider: Provider) -> ProviderProfile:
    return PROFILES[provider]


def default_rules(provider: Provider, params: ProfileParams) -> AccountRules:
    profile = provider_profile(provider)
    if params.account_type not in profile.allowed_account_types:
        allowed = ", ".join(sorted(t.value for t in profile.allowed_account_types))
        raise ValidationFailed(
            f"{provider} accounts are of type {allowed}, not {params.account_type}", code="account_type_not_allowed"
        )
    return profile.build_rules(params)
