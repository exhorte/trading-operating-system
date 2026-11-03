"""What the broker says about an account, read once identifiers are given (ADR 0020): never what the user claims.

Pure helpers and the read model. The service (``AccountService.discover``) does the I/O; this module decides what the
facts *mean* — which provider the server name belongs to, demo or real, how the broker spells the instruments, and what
the capital can honestly be taken to be.

**The initial capital is the one figure a broker does not state.** An account shows its balance today, not what it was
funded with. The best evidence is the first deposit in the broker's own history (a balance operation); without it the
current balance is only a *proposal*, flagged as such (``reliable=False``) — the grid of ADR 0019 is measured against the
initial capital, so the trader confirms it, the core never decides it silently.

No holder name, no password: the model carries neither (``tests/architecture`` keeps secrets out of response models).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from trading_os.domain.accounts.models import Environment, Provider
from trading_os.domain.primitives import DomainModel

# The instruments the first version trades (mission §4). The suffix is read from these, not from a table of brokers.
INSTRUMENTS: tuple[str, ...] = ("EURUSD", "XAUUSD")
MAX_SUFFIX_LENGTH = 4

# MT5 ``ACCOUNT_TRADE_MODE_*`` and ``DEAL_TYPE_BALANCE``.
TRADE_MODE_DEMO, TRADE_MODE_CONTEST, TRADE_MODE_REAL = 0, 1, 2
DEAL_TYPE_BALANCE = 2


class DiscoveredSymbol(DomainModel):
    canonical: str
    broker_name: str
    volume_min: float
    volume_step: float
    contract_size: float
    tick_size: float
    tick_value: float
    digits: int
    spread: float | None  # price units; None when the market has no quote (closed)
    tradable: bool


class CapitalProposal(DomainModel):
    amount: float
    source: Literal["first_deposit", "current_balance"]
    at: datetime | None  # when the deposit was made; None for the current balance
    reliable: bool  # a deposit read from the broker's history is evidence; a balance that has moved is not


class DiscoveredAccount(DomainModel):
    login: int
    server: str
    company: str
    currency: str
    leverage: int
    balance: float
    equity: float
    margin: float
    margin_free: float
    margin_level: float | None  # None while no margin is used
    trade_mode: Literal["demo", "contest", "real", "unknown"]
    margin_mode: Literal["netting", "exchange", "hedging", "unknown"]
    fifo_close: bool
    trade_allowed: bool
    trade_expert: bool
    open_positions: int
    pending_orders: int
    provider: Provider | None  # recognised from the server and the company; None = not one we know
    environment: Environment | None  # from the account's trade mode; None = unknown, the user decides
    symbol_suffix: str | None
    symbols: list[DiscoveredSymbol]
    capital: CapitalProposal
    suggested_name: str
    terminal_path: str | None
    warnings: list[str]


def recognise_provider(server: str, company: str) -> Provider | None:
    """The provider the *broker's own* names point to. Never the user's say-so: an FTMO form filled with an Exness server
    must be noticed, not obeyed."""
    text = f"{server} {company}".lower()
    found = [provider for provider in Provider if provider.value.lower() in text]
    return found[0] if len(found) == 1 else None


def environment_of(trade_mode: int) -> Environment | None:
    if trade_mode in (TRADE_MODE_DEMO, TRADE_MODE_CONTEST):
        return Environment.DEMO
    if trade_mode == TRADE_MODE_REAL:
        return Environment.LIVE
    return None


def broker_name_of(canonical: str, names: Sequence[str]) -> str | None:
    """How this broker spells ``canonical``: itself (FTMO, Exness Pro), or with a short suffix (Exness Standard: ``…m``).
    The plainest spelling wins; the others are left alone."""
    if canonical in names:
        return canonical
    candidates = [
        name
        for name in names
        if name.startswith(canonical)
        and 0 < len(name) - len(canonical) <= MAX_SUFFIX_LENGTH
        and name[len(canonical) :].replace(".", "").replace("_", "").isalnum()
    ]
    return min(candidates, key=lambda name: (len(name), name)) if candidates else None


def suffix_of(spellings: dict[str, str]) -> tuple[str | None, list[str]]:
    """The suffix every instrument shares, and a warning for each one that does not follow it."""
    suffixes = {canonical: name[len(canonical) :] for canonical, name in spellings.items()}
    if not suffixes:
        return None, []
    first = next(iter(suffixes.values()))
    odd = [
        f"{canonical} is spelled {spellings[canonical]!r}, not with {first!r}"
        for canonical, s in suffixes.items()
        if s != first
    ]
    return first, odd


def capital_proposal(first_deposit: tuple[float, datetime] | None, balance: float) -> CapitalProposal:
    if first_deposit is not None:
        amount, at = first_deposit
        return CapitalProposal(amount=round(amount, 2), source="first_deposit", at=at, reliable=True)
    return CapitalProposal(amount=round(balance, 2), source="current_balance", at=None, reliable=False)


def suggested_name(provider: Provider | None, company: str, login: int, environment: Environment | None) -> str:
    brand = provider.value.title() if provider else (company.split(" ")[0] if company else "MT5")
    suffix = " démo" if environment is Environment.DEMO else ""
    return f"{brand} {login}{suffix}"
