"""Representative **simulated** facts for each provider and product (ADR 0036).

None of this is a live reading. The server and company names are plausible spellings built to match what the architecture
recognises; the real values come from a terminal, and only the contract tests (``-m live_mt5``) say what a terminal really
reports. A test using these proves the *logic* for that shape of account, never that a provider's terminal looks like this.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trading_os.domain.accounts.models import AccountType, Environment, FtmoChallenge, Provider
from trading_os.domain.providers.identity import IdentityFacts

OBSERVED_AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def exness_standard(*, real: bool = False, **changes: object) -> IdentityFacts:
    facts = IdentityFacts(
        login=1_000_001,
        server="Exness-MT5Real10" if real else "Exness-MT5Trial10",
        company="Exness Technologies Ltd",
        terminal_company="Exness Technologies Ltd",
        trade_mode="real" if real else "demo",
        currency="USD",
        leverage=100,
        observed_suffixes=("m",),
        declared_provider=Provider.EXNESS,
        declared_environment=Environment.LIVE if real else Environment.DEMO,
        declared_account_type=AccountType.DIRECT,
        observed_at=OBSERVED_AT,
    )
    return facts.model_copy(update=changes)


def ftmo(
    *,
    type_: str = "2-step",
    phase: str = "challenge",
    variant: str = "standard",
    declared: bool = True,
    **changes: object,
) -> IdentityFacts:
    challenge = (
        FtmoChallenge.model_validate({"type": type_, "accountSize": 100_000, "phase": phase, "variant": variant})
        if declared
        else None
    )
    facts = IdentityFacts(
        login=2_000_002,
        server="FTMO-Server3",
        company="FTMO Global Markets Ltd",
        terminal_company="FTMO Global Markets Ltd",
        trade_mode="demo",  # whatever the terminal says: FTMO is simulated trading, the mode is not what identifies it
        currency="USD",
        leverage=100,
        observed_suffixes=("",),
        declared_provider=Provider.FTMO,
        declared_environment=Environment.SIMULATED,
        declared_account_type={
            "challenge": AccountType.PROP_CHALLENGE,
            "verification": AccountType.PROP_VERIFICATION,
            "funded": AccountType.PROP_FUNDED,
        }[phase],
        challenge=challenge,
        observed_at=OBSERVED_AT,
    )
    return facts.model_copy(update=changes)


def ftmo_challenge_1step(**changes: object) -> IdentityFacts:
    return ftmo(type_="1-step", phase="challenge", **changes)


def ftmo_challenge_2step(**changes: object) -> IdentityFacts:
    return ftmo(type_="2-step", phase="challenge", **changes)


def ftmo_verification(**changes: object) -> IdentityFacts:
    return ftmo(type_="2-step", phase="verification", **changes)


def ftmo_account_1step(**changes: object) -> IdentityFacts:
    return ftmo(type_="1-step", phase="funded", **changes)


def ftmo_account_2step(**changes: object) -> IdentityFacts:
    return ftmo(type_="2-step", phase="funded", **changes)


def ftmo_swing(**changes: object) -> IdentityFacts:
    return ftmo(type_="2-step", phase="funded", variant="swing", **{"leverage": 30, **changes})
