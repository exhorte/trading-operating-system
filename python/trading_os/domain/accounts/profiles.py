"""Provider profiles: what makes an FTMO account and an Exness account behave differently — **without a single**
``if provider == …`` anywhere else. A registry maps each provider to the factory of its default rules.

Only facts that were sourced are encoded. FTMO's 2-Step *Challenge* phase comes from the trader's own MetriX exports
(4 minimum trading days, 10 % profit target, −5 % daily and −10 % overall of the initial size); verification, funded
and 1-step were never shown in those exports and stay ``None`` — « non sourcé », not guessed (TODO(FTMO-rules)).
The discipline limits (risk per trade, trades per day…) are the trader's own and identical across providers; the
numbers the user fixed on 2026-09-26 are theirs to write into the account rules, not defaults baked into code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

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
from trading_os.domain.risk.policy import DrawdownPolicy, RiskProfile
from trading_os.shared.errors import ValidationFailed


class ProfileParams(DomainModel):
    account_type: AccountType
    reference_balance: float | None = None  # direct accounts: the capital the trader commits
    challenge: FtmoChallenge | None = None  # prop accounts


@dataclass(frozen=True)
class ProviderProfile:
    provider: Provider
    symbol_suffix: str
    allowed_account_types: frozenset[AccountType]
    build_rules: Callable[[ProfileParams], AccountRules]


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
    challenge = params.challenge or FtmoChallenge(type="2-step", account_size=10_000, phase=phase)
    if challenge.phase != phase:
        raise ValidationFailed(
            f"challenge phase {challenge.phase!r} does not match the account type {params.account_type}",
            code="phase_mismatch",
        )
    min_days, target = _ftmo_objectives(challenge)
    return AccountRules(
        risk_profile=RiskProfile(
            drawdown=DrawdownPolicy(
                daily_loss_limit_percent=5.0, max_drawdown_limit_percent=10.0, reference_balance=challenge.account_size
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
    ),
    Provider.FTMO: ProviderProfile(
        provider=Provider.FTMO,
        symbol_suffix="",
        allowed_account_types=frozenset(
            {AccountType.PROP_CHALLENGE, AccountType.PROP_VERIFICATION, AccountType.PROP_FUNDED}
        ),
        build_rules=_build_ftmo,
    ),
}


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
