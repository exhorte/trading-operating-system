"""The account profile (ADR 0036): one read-only view of *which* account this is, assembled from what the system already holds.

Nothing here is a new source of truth. The stored account says what the user declared; the snapshot says what the terminal reports
now; the identification says how sure we are of who the provider is and what the product is. The profile puts them side by side —
declared next to observed — so a disagreement is visible rather than silently resolved.

A figure the terminal did not give is ``None``, shown as unknown. ``last_synchronized_at`` is the time of the **terminal's** last
reading, never the time the profile was built.
"""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.accounts.models import Account, AccountSnapshot
from trading_os.domain.primitives import DomainModel
from trading_os.domain.providers.commission import CommissionReading
from trading_os.domain.providers.identity import AccountIdentification


class TradingPermissions(DomainModel):
    terminal_trade_allowed: bool | None  # « Allow Algo Trading » at the terminal's account level
    expert_trading_allowed: bool | None  # the account allows expert advisors
    account_trading_enabled: bool  # the user's « Disable Trading » switch
    margin_mode: str | None
    fifo_close: bool | None


class AccountProfile(DomainModel):
    account_id: str
    name: str
    # who
    provider: str | None  # observed: what the terminal's names say
    declared_provider: str
    broker: str | None  # the company the account reports
    server: str
    login: int
    currency: str
    account_type: str
    phase: str | None  # the declared phase of a prop contract; None where there is none
    broker_product: str
    evaluation_product: str  # the contract whose rules apply (the broker's own, or a rehearsed one)
    rules_rehearsal: bool
    account_mode: str | None  # DEMO / REAL / SIMULATED
    declared_environment: str
    # what the terminal says now
    leverage: int | None
    initial_capital: float | None  # the capital the limits are measured against: declared, never read from the balance
    balance: float | None
    equity: float | None
    free_margin: float | None
    used_margin: float | None
    margin_level: float | None
    commission: (
        CommissionReading | None
    )  # what the account pays and where that figure comes from: observed, documentary or assumed
    permissions: TradingPermissions
    # how sure
    identification: AccountIdentification
    rule_set_id: str | None
    rule_version: str | None
    last_synchronized_at: datetime | None
    problems: tuple[str, ...]
    computed_at: datetime


def assemble_profile(
    account: Account,
    *,
    snapshot: AccountSnapshot | None,
    identification: AccountIdentification,
    rule_version: str | None,
    now: datetime,
    commission: CommissionReading | None = None,
) -> AccountProfile:
    challenge = account.trading_rules.challenge
    problems: list[str] = []
    if snapshot is None:
        problems.append("the terminal has not reported this account yet: no balance, equity or margin")
    problems += [f"{blocker.value}" for blocker in identification.blockers]
    return AccountProfile(
        account_id=account.id,
        name=account.name,
        provider=identification.provider.value if identification.provider else None,
        declared_provider=account.provider.value,
        broker=snapshot.broker if snapshot else None,
        server=account.server,
        login=account.login,
        currency=account.currency,
        account_type=account.account_type.value,
        phase=challenge.phase if challenge else None,
        broker_product=identification.broker_product.value,
        evaluation_product=identification.rules_product.value,
        rules_rehearsal=identification.rules_rehearsal,
        account_mode=identification.account_mode,
        declared_environment=account.environment.value,
        leverage=snapshot.leverage if snapshot else None,
        initial_capital=account.risk_profile.drawdown.reference_balance,
        balance=snapshot.balance if snapshot else None,
        equity=snapshot.equity if snapshot else None,
        free_margin=snapshot.free_margin if snapshot else None,
        used_margin=snapshot.margin if snapshot else None,
        margin_level=snapshot.margin_level if snapshot else None,
        commission=commission,
        permissions=TradingPermissions(
            terminal_trade_allowed=snapshot.trade_allowed if snapshot else None,
            expert_trading_allowed=snapshot.trade_expert if snapshot else None,
            account_trading_enabled=account.trading_enabled,
            margin_mode=snapshot.margin_mode if snapshot else None,
            fifo_close=snapshot.fifo_close if snapshot else None,
        ),
        identification=identification,
        rule_set_id=identification.rule_set_id,
        rule_version=rule_version,
        last_synchronized_at=snapshot.observed_at if snapshot else None,
        problems=tuple(problems),
        computed_at=now,
    )


__all__ = ["AccountProfile", "TradingPermissions", "assemble_profile"]
