"""Accounts. An ``Account`` describes *which* account and *how it is to be traded* — never a secret.

No password, no token, no key: credentials live behind ``CredentialStore`` (infrastructure) and are not a field of
anything here, so no event, API response or database column built from these models can carry one.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.market.sessions import ACCOUNT_TRADING_WINDOWS, TradingWindow
from trading_os.domain.primitives import DomainModel
from trading_os.domain.risk.policy import RiskProfile


class Provider(StrEnum):
    EXNESS = "EXNESS"
    FTMO = "FTMO"


class Platform(StrEnum):
    MT5 = "MT5"


class AccountType(StrEnum):
    DIRECT = "DIRECT"  # a broker account traded directly
    PROP_CHALLENGE = "PROP_CHALLENGE"
    PROP_VERIFICATION = "PROP_VERIFICATION"
    PROP_FUNDED = "PROP_FUNDED"


class Environment(StrEnum):
    DEMO = "DEMO"
    SIMULATED = "SIMULATED"
    LIVE = "LIVE"


class AccountStatus(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


class FtmoChallenge(DomainModel):
    """The challenge being traded — the only FTMO configuration that varies between challenges. Every FTMO limit is
    a percentage of ``account_size`` (fixed for the whole challenge), never of the current balance."""

    type: Literal["1-step", "2-step"]
    account_size: float = Field(ge=1_000, le=10_000_000)
    phase: Literal["challenge", "verification", "funded"]


class TradingRules(DomainModel):
    allowed_symbols: tuple[str, ...] | None = None  # broker-side names; None = whatever the broker offers
    # New York local time. The envelope the Risk Engine's session gate enforces: a new account starts with every hour a strategy may
    # trade (ADR 0030); each strategy keeps to its own windows inside it.
    trading_windows: tuple[TradingWindow, ...] = ACCOUNT_TRADING_WINDOWS
    challenge: FtmoChallenge | None = None
    # What a prop phase requires beyond staying inside the limits. None = "not sourced" — shown as such, never guessed.
    min_trading_days: int | None = Field(default=None, ge=1)
    profit_target_percent: float | None = Field(default=None, gt=0)


class ExecutionLimits(DomainModel):
    max_slippage_points: int = Field(default=10, ge=0)
    command_ttl_seconds: int = Field(default=60, ge=5, le=600)
    commission_per_lot_round_trip: float = Field(default=0.0, ge=0)  # account currency
    cost_threshold: float = Field(default=0.25, gt=0)  # S01 « porte de coût » c ≤ 0.25
    # Optional per-symbol spread ceilings (price units). Empty = no fixed cap (ADR 0015 amendment).
    max_spread_by_symbol: dict[str, float] = Field(default_factory=dict)


class ExecutionProfile(DomainModel):
    # Highest mode this account may ever reach. OBSERVE until the user raises it — a deliberate, per-account gesture.
    max_mode: AutonomyMode = AutonomyMode.OBSERVE
    limits: ExecutionLimits = ExecutionLimits()


class AccountRules(DomainModel):
    """The versioned part of an account: what the anti-tilt ledger records and resolves."""

    risk_profile: RiskProfile
    trading_rules: TradingRules
    execution_profile: ExecutionProfile


class Account(DomainModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]{1,47}$")
    name: str = Field(min_length=1, max_length=80)
    provider: Provider
    platform: Platform = Platform.MT5
    account_type: AccountType
    login: int = Field(gt=0)
    server: str = Field(min_length=1, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    environment: Environment
    terminal_path: str | None = None  # one terminal per account that must be connected at the same time
    symbol_suffix: str = ""  # how this broker names instruments ("m" on Exness Standard)
    status: AccountStatus = AccountStatus.DISCONNECTED
    status_detail: str | None = None  # why it is in ERROR — never contains a secret
    trading_enabled: bool = True  # the user's « Disable Trading » switch
    risk_profile: RiskProfile
    trading_rules: TradingRules
    execution_profile: ExecutionProfile
    created_at: datetime

    @property
    def rules(self) -> AccountRules:
        return AccountRules(
            risk_profile=self.risk_profile, trading_rules=self.trading_rules, execution_profile=self.execution_profile
        )

    def with_rules(self, rules: AccountRules) -> Account:
        return self.model_copy(
            update={
                "risk_profile": rules.risk_profile,
                "trading_rules": rules.trading_rules,
                "execution_profile": rules.execution_profile,
            }
        )


class AccountSnapshot(DomainModel):
    """Live figures of the attached account, as MT5's account window shows them. Never the holder's name."""

    account_id: str
    label: str
    broker: str
    currency: str
    balance: float
    equity: float
    daily_pnl: float = 0.0
    daily_drawdown_percent: float = 0.0
    total_drawdown_percent: float = 0.0
    open_risk_percent: float = 0.0
    margin: float | None = None
    free_margin: float | None = None
    margin_level: float | None = None
    server: str | None = None
    trade_mode: Literal["demo", "contest", "real", "unknown"] | None = None
    leverage: int | None = None
    margin_mode: Literal["hedging", "netting", "exchange", "unknown"] | None = None
    fifo_close: bool | None = None
    trade_allowed: bool | None = None
    trade_expert: bool | None = None
    observed_at: datetime
