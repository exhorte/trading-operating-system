"""Accounts: the registry, the connections, the single active account, the trading switch, and the versioned rules.

* An account is *configuration* (``Account``): no secret. A connection is *runtime* (``AccountSession``): one MT5 client per
  connected account. A password is handed to ``connect`` and forgotten — or read from the ``CredentialStore`` the user
  opted into — and never stored on the session.
* **Only one account is connected at a time** (ADR 0021), and the connected account is the active one. Only it receives
  automatic commands; a human command names its ``accountId`` explicitly and must match the account really attached
  (ADR 0010). Connecting another account means detaching the first, which is refused while it could hide risk.
* **Switching and disconnecting are refused while they could hide risk** (ADR 0013): open positions, pending orders, an
  armed session, a command in doubt. The services that know register a *guard*; this service asks them.
* Rule changes go through the anti-tilt ledger: applied at once only when no session is in progress, else deferred to the
  next trading-day anchor (ADR 0007).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import Field, SecretStr

from trading_os.domain.accounts import anti_tilt
from trading_os.domain.accounts import discovery as broker_facts
from trading_os.domain.accounts.anti_tilt import GuardDecision
from trading_os.domain.accounts.discovery import DiscoveredAccount, DiscoveredSymbol
from trading_os.domain.accounts.models import (
    Account,
    AccountRules,
    AccountStatus,
    AccountType,
    Environment,
    FtmoChallenge,
    Provider,
)
from trading_os.domain.accounts.profiles import (
    ProfileParams,
    apply_provider_ceilings,
    default_rules,
    provider_ceilings,
    provider_profile,
)
from trading_os.domain.accounts.rules_ledger import (
    CancelOutcome,
    RuleResolution,
    RuleVersion,
    VersionStatus,
    cancel_outcome,
    new_version,
    resolve_rules,
    version_status,
)
from trading_os.domain.events import (
    AccountArchived,
    AccountConnected,
    AccountCreated,
    AccountDisconnected,
    AccountErrored,
    AccountRulesChanged,
    AccountTradingToggled,
    AccountUpdated,
    ActiveAccountChanged,
)
from trading_os.domain.primitives import DomainModel
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.mt5.client import MARGIN_MODES, TRADE_MODES, Mt5AccountInfo, Mt5Client
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.infrastructure.security.credentials import CredentialStore
from trading_os.shared.errors import Conflict, NotFound, TradingOsError, Unavailable, ValidationFailed
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

ACTIVE_ACCOUNT_KEY = "active_account"
DEPOSIT_HISTORY_START = datetime(2010, 1, 1, tzinfo=UTC)  # before any MT5 account existed

# A guard answers « may this account be switched away from / disconnected right now? » with a refusal, or None.
Guard = Callable[[str], Awaitable[str | None]]


class Mt5Factory(Protocol):
    """Builds the MT5 client of one account: a worker process per terminal in production, an in-memory terminal in tests
    and in the simulated mode."""

    def __call__(self, account: Account) -> Mt5Client: ...


class AccountCreate(DomainModel):
    name: str = Field(min_length=1, max_length=80)
    provider: Provider
    account_type: AccountType
    login: int = Field(gt=0)
    server: str = Field(min_length=1, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    environment: Environment
    id: str | None = None
    terminal_path: str | None = None
    symbol_suffix: str | None = None
    reference_balance: float | None = Field(default=None, gt=0)  # direct accounts: the capital committed
    challenge: FtmoChallenge | None = None  # prop accounts
    # The provider whose rules to rehearse when it is not the broker's: an Exness *demo* account can follow the FTMO
    # profile (ADR 0020). Never on a real account: a prop profile on real money would be a lie about the contract.
    rules_profile: Provider | None = None


@dataclass
class AccountSession:
    account: Account
    client: Mt5Client
    info: Mt5AccountInfo
    connected_at: datetime


class RuleVersionView(RuleVersion):
    """A version as the cockpit reads it: what the ledger recorded, and what it is worth *now* — in effect, waiting,
    replaced or withdrawn — and whether it may still be withdrawn. The core answers; the page does not re-derive."""

    status: VersionStatus
    cancellable: bool


class RulesOverview(DomainModel):
    account_id: str
    resolution: RuleResolution
    versions: list[RuleVersionView]  # newest first
    # What a change saved at this instant would do: applied at once, or kept for the next trading day, and why. The form
    # shows it *before* the click; ``request_rules`` decides again at the click, with the same function.
    guard: GuardDecision
    evaluated_at: datetime


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")[:30] or "acct"


class AccountService:
    def __init__(
        self,
        *,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        credentials: CredentialStore,
        mt5_factory: Mt5Factory,
        open_positions: Callable[[], int] = lambda: 0,
    ) -> None:
        self._repos = repos
        self._events = events
        self._clock = clock
        self._credentials = credentials
        self._factory = mt5_factory
        self._open_positions = open_positions
        self._sessions: dict[str, AccountSession] = {}
        self._connecting: set[str] = set()
        self._errors: dict[str, str] = {}
        self._guards: list[Guard] = []
        self._lock = asyncio.Lock()
        self.active_account_id: str | None = None

    # ------------------------------------------------------------------------------------------ wiring
    def add_guard(self, guard: Guard) -> None:
        self._guards.append(guard)

    def set_open_positions_provider(self, provider: Callable[[], int]) -> None:
        self._open_positions = provider

    async def start(self, initial_active: str | None = None) -> None:
        stored = await self._repos.state.get(ACTIVE_ACCOUNT_KEY)
        candidate = (stored or {}).get("id") if isinstance(stored, dict) else None
        candidate = candidate or initial_active
        if candidate and await self._repos.accounts.get(candidate):
            self.active_account_id = candidate

    async def stop(self) -> None:
        for account_id in list(self._sessions):
            await self._drop(account_id, reason="shutdown")

    # ------------------------------------------------------------------------------------------ reading
    def session(self, account_id: str) -> AccountSession | None:
        return self._sessions.get(account_id)

    def sessions(self) -> list[AccountSession]:
        return list(self._sessions.values())

    def is_connected(self, account_id: str) -> bool:
        return account_id in self._sessions

    async def attached_account_id(self, account_id: str) -> str | None:
        """Which of our accounts the terminal is *really* logged into right now — read live, never assumed (ADR 0010).
        ``None`` when the account is not connected or the terminal cannot be read; ``login:<n>`` when the terminal is
        logged into an account the Trading OS does not know."""
        session = self._sessions.get(account_id)
        if session is None:
            return None
        try:
            info = await session.client.account_info()
        except (WorkerError, Unavailable):
            return None
        if info.login == session.account.login:
            return account_id
        for other in await self._repos.accounts.all():
            if other.login == info.login:
                return other.id
        return f"login:{info.login}"

    def connected_ids(self) -> list[str]:
        return list(self._sessions)

    def _status_of(self, account_id: str) -> tuple[AccountStatus, str | None]:
        if account_id in self._sessions:
            return AccountStatus.CONNECTED, None
        if account_id in self._connecting:
            return AccountStatus.CONNECTING, None
        if account_id in self._errors:
            return AccountStatus.ERROR, self._errors[account_id]
        return AccountStatus.DISCONNECTED, None

    def _view(self, account: Account) -> Account:
        status, detail = self._status_of(account.id)
        return account.model_copy(update={"status": status, "status_detail": detail})

    async def accounts(self) -> list[Account]:
        return [self._view(a) for a in await self._repos.accounts.all()]

    async def get(self, account_id: str) -> Account:
        return self._view(await self._repos.accounts.require(account_id))

    async def effective(self, account_id: str) -> Account:
        """The account with the rules that govern it *now* (ledger resolved against the current trading-day anchor)."""
        account = await self._repos.accounts.require(account_id)
        resolution = await self._resolution(account)
        ceilings = provider_ceilings(resolution.rules.trading_rules.challenge)
        return self._view(account.with_rules(apply_provider_ceilings(resolution.rules, ceilings)))

    async def _resolution(self, account: Account) -> RuleResolution:
        versions = await self._repos.rules.for_account(account.id)
        today = await self._repos.risk.today(account.id, self._clock.now())
        return resolve_rules(versions, today.day_anchor_starts_at_utc, account.rules)

    # ------------------------------------------------------------------------------------------ registry
    async def create(self, spec: AccountCreate) -> Account:
        profile = provider_profile(spec.provider)
        rules_provider = spec.rules_profile or spec.provider
        if rules_provider is not spec.provider and spec.environment is Environment.LIVE:
            raise ValidationFailed(
                f"the {rules_provider.value} rules profile can be rehearsed on a demo account only, not on a real one",
                code="rules_profile_demo_only",
            )
        rules = default_rules(
            rules_provider,
            ProfileParams(
                account_type=spec.account_type, reference_balance=spec.reference_balance, challenge=spec.challenge
            ),
        )
        account_id = spec.id or f"{spec.provider.value.lower()}-{spec.login}"
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_\-]{1,47}$", account_id):
            account_id = f"{spec.provider.value.lower()}-{_slug(account_id)}"
        account = Account(
            id=account_id,
            name=spec.name,
            provider=spec.provider,
            account_type=spec.account_type,
            login=spec.login,
            server=spec.server,
            currency=spec.currency.upper(),
            environment=spec.environment,
            terminal_path=spec.terminal_path,
            symbol_suffix=spec.symbol_suffix if spec.symbol_suffix is not None else profile.symbol_suffix,
            risk_profile=rules.risk_profile,
            trading_rules=rules.trading_rules,
            execution_profile=rules.execution_profile,
            created_at=self._clock.now(),
        )
        await self._repos.accounts.insert(account)
        await self._events.publish(
            AccountCreated(
                account_id=account.id,
                name=account.name,
                provider=account.provider.value,
                environment=account.environment,
            )
        )
        return self._view(account)

    async def update(
        self, account_id: str, *, name: str | None = None, terminal_path: str | None = None,
        symbol_suffix: str | None = None,
    ) -> Account:  # fmt: skip
        if account_id in self._sessions and (terminal_path is not None or symbol_suffix is not None):
            raise Conflict(
                "disconnect the account before changing its terminal or symbol suffix", code="account_connected"
            )
        await self._repos.accounts.update_details(
            account_id, name=name, terminal_path=terminal_path, symbol_suffix=symbol_suffix
        )
        changed = [
            k
            for k, v in {"name": name, "terminal_path": terminal_path, "symbol_suffix": symbol_suffix}.items()
            if v is not None
        ]
        await self._events.publish(AccountUpdated(account_id=account_id, fields=changed))
        return await self.get(account_id)

    async def archive(self, account_id: str) -> None:
        if account_id in self._sessions:
            raise Conflict("disconnect the account before archiving it", code="account_connected")
        await self._repos.accounts.archive(account_id, self._clock.now())
        if self.active_account_id == account_id:
            await self._set_active_id(None)
        await self._events.publish(AccountArchived(account_id=account_id))

    async def set_trading_enabled(self, account_id: str, enabled: bool) -> Account:
        await self._repos.accounts.set_trading_enabled(account_id, enabled)
        await self._events.publish(AccountTradingToggled(account_id=account_id, enabled=enabled))
        return await self.get(account_id)

    # ------------------------------------------------------------------------------------------ discovery
    async def discover(
        self, *, login: int, server: str, password: SecretStr | None = None, terminal_path: str | None = None
    ) -> DiscoveredAccount:
        """Attach to the terminal with these identifiers, **read** what the broker says about the account, detach, forget.

        Read-only by construction (the worker's whitelist has no order function), nothing is registered and no password is kept:
        the terminal stays logged in, so registering and connecting afterwards needs none. Refused while another account holds
        another account: one account is connected at a time, and one terminal answers for one account."""
        now = self._clock.now()
        rules = default_rules(Provider.EXNESS, ProfileParams(account_type=AccountType.DIRECT))
        probe = Account(
            id=f"probe-{login}", name="probe", provider=Provider.EXNESS, account_type=AccountType.DIRECT, login=login,
            server=server, environment=Environment.DEMO, terminal_path=terminal_path, risk_profile=rules.risk_profile,
            trading_rules=rules.trading_rules, execution_profile=rules.execution_profile, created_at=now,
        )  # fmt: skip
        async with self._lock:
            self._require_none_connected_but(probe.id)
            client = self._factory(probe)
            try:
                info = await client.connect(login=login, server=server, terminal_path=terminal_path, password=password)
                return await self._read_facts(client, info, terminal_path, now)
            finally:
                with contextlib.suppress(TradingOsError):
                    await client.disconnect()  # the worker of a probe never lingers; the terminal keeps its login

    async def _read_facts(
        self, client: Mt5Client, info: Mt5AccountInfo, terminal_path: str | None, now: datetime
    ) -> DiscoveredAccount:
        warnings: list[str] = []
        positions, orders = await client.positions(), await client.orders()
        names = await client.symbol_names()
        spellings = {c: n for c in broker_facts.INSTRUMENTS if (n := broker_facts.broker_name_of(c, names)) is not None}
        for canonical in broker_facts.INSTRUMENTS:
            if canonical not in spellings:
                warnings.append(f"{canonical} is not among this broker's symbols")
        suffix, odd = broker_facts.suffix_of(spellings)
        warnings += odd

        symbols: list[DiscoveredSymbol] = []
        for canonical, broker_name in spellings.items():
            await client.select_symbol(broker_name)  # a symbol outside Market Watch has no spec or quote to read
            spec = await client.symbol_spec(broker_name)
            if spec is None:
                warnings.append(f"{broker_name}: the broker gave no specification")
                continue
            tick = await client.tick(broker_name)
            symbols.append(
                DiscoveredSymbol(
                    canonical=canonical,
                    broker_name=broker_name,
                    volume_min=spec.volume_min,
                    volume_step=spec.volume_step,
                    contract_size=spec.contract_size,
                    tick_size=spec.tick_size,
                    tick_value=spec.tick_value,
                    digits=spec.digits,
                    spread=tick.spread if tick else None,
                    tradable=spec.trade_allowed,
                )
            )

        provider = broker_facts.recognise_provider(info.server, info.company)
        environment = broker_facts.environment_of(info.trade_mode)
        if provider is None:
            warnings.append("neither the server nor the company is Exness or FTMO: choose the provider yourself")
        if environment is None:
            warnings.append("the account's mode (demo / real) is unknown: choose the environment yourself")
        if not info.trade_allowed:
            warnings.append("trading is not allowed on this account")
        if not info.trade_expert:
            warnings.append("automated trading is off for this account: the execution agent could not place orders")
        if MARGIN_MODES.get(info.margin_mode) != "hedging":
            warnings.append("this is not a hedging account")
        if positions or orders:
            warnings.append(
                f"{len(positions)} open position(s) and {len(orders)} pending order(s) already on the account"
            )

        return DiscoveredAccount(
            login=info.login, server=info.server, company=info.company, currency=info.currency, leverage=info.leverage,
            balance=info.balance, equity=info.equity, margin=info.margin, margin_free=info.margin_free,
            margin_level=info.margin_level if info.margin > 0 else None,
            trade_mode=TRADE_MODES.get(info.trade_mode, "unknown"),
            margin_mode=MARGIN_MODES.get(info.margin_mode, "unknown"),
            fifo_close=info.fifo_close, trade_allowed=info.trade_allowed, trade_expert=info.trade_expert,
            open_positions=len(positions), pending_orders=len(orders), provider=provider, environment=environment,
            symbol_suffix=suffix, symbols=symbols,
            capital=broker_facts.capital_proposal(await self._first_deposit(client, now), info.balance),
            suggested_name=broker_facts.suggested_name(provider, info.company, info.login, environment),
            terminal_path=terminal_path, warnings=warnings,
        )  # fmt: skip

    @staticmethod
    async def _first_deposit(client: Mt5Client, now: datetime) -> tuple[float, datetime] | None:
        """The first balance operation in the broker's own history: the best evidence of what the account was funded with."""
        try:
            deals = await client.deals_between(DEPOSIT_HISTORY_START, now + timedelta(days=1))
        except (WorkerError, Unavailable):
            return None  # no history to read is not an error: the capital is then only proposed from the balance
        deposits = sorted(
            (d for d in deals if d.type == broker_facts.DEAL_TYPE_BALANCE and d.profit > 0), key=lambda d: d.time
        )
        return (deposits[0].profit, client.to_utc(deposits[0].time)) if deposits else None

    # ------------------------------------------------------------------------------------------ connections
    async def connect(self, account_id: str, password: SecretStr | None = None) -> Account:
        async with self._lock:
            account = await self._repos.accounts.require(account_id)
            if account_id in self._sessions:
                return self._view(account)
            self._require_none_connected_but(account_id)
            self._connecting.add(account_id)
            client = self._factory(account)
            try:
                secret = password or await self._credentials.get(account_id)
                info = await client.connect(
                    login=account.login, server=account.server, terminal_path=account.terminal_path, password=secret
                )
            except TradingOsError as error:
                self._connecting.discard(account_id)
                self._errors[account_id] = error.safe_message
                await self._events.publish(
                    AccountErrored(account_id=account_id, code=error.code, detail=error.safe_message)
                )
                with contextlib.suppress(TradingOsError):
                    await client.disconnect()  # the worker process of a failed attempt must not linger
                raise
            self._connecting.discard(account_id)
            self._errors.pop(account_id, None)
            self._sessions[account_id] = AccountSession(account, client, info, self._clock.now())
        await self._events.publish(
            AccountConnected(
                account_id=account_id, server=info.server, currency=info.currency, environment=account.environment
            )
        )
        await self._set_active_id(account_id)  # the only connected account is the active one (ADR 0021)
        return self._view(account)

    def _require_none_connected_but(self, account_id: str) -> None:
        """One account at a time (ADR 0021): refused, with the account to detach first, while another one is connected."""
        for other in self._sessions.values():
            if other.account.id != account_id:
                raise Conflict(
                    f"only one account can be connected at a time: {other.account.name!r} is connected — detach it first",
                    code="another_account_connected",
                    details={"connectedAccountId": other.account.id, "connectedAccountName": other.account.name},
                )

    async def disconnect(self, account_id: str, *, force: bool = False, reason: str = "user") -> Account:
        async with self._lock:
            account = await self._repos.accounts.require(account_id)
            if account_id not in self._sessions:
                return self._view(account)
            if not force:
                refusals = await self._refusals(account_id)
                if refusals:
                    raise Conflict(
                        "cannot disconnect: " + "; ".join(refusals), code="disconnect_refused",
                        details={"reasons": refusals},
                    )  # fmt: skip
            await self._drop(account_id, reason=reason)
        return await self.get(account_id)

    async def reconnect(self, account_id: str) -> Account:
        """Close and re-attach. The password is gone (never kept): the vault, if the user opted into one, or the terminal's
        own saved login supplies it."""
        if account_id in self._sessions:
            await self.disconnect(account_id, force=True, reason="reconnect")
        return await self.connect(account_id)

    async def mark_lost(self, account_id: str, reason: str) -> None:
        """The link to the terminal broke (the supervisor noticed): forget the session, remember why."""
        async with self._lock:
            if account_id not in self._sessions:
                return
            self._errors[account_id] = reason
            await self._drop(account_id, reason=reason)
        await self._events.publish(AccountErrored(account_id=account_id, code="connection_lost", detail=reason))

    async def _drop(self, account_id: str, *, reason: str) -> None:
        session = self._sessions.pop(account_id, None)
        if session is None:
            return
        try:
            await session.client.disconnect()
        except TradingOsError:
            logger.warning("closing the MT5 client of %s failed", account_id, exc_info=True)
        await self._events.publish(AccountDisconnected(account_id=account_id, reason=reason))

    async def _refusals(self, account_id: str) -> list[str]:
        found: list[str] = []
        for guard in self._guards:
            reason = await guard(account_id)
            if reason:
                found.append(reason)
        return found

    # ------------------------------------------------------------------------------------------ active account
    async def set_active(self, account_id: str) -> Account:
        async with self._lock:
            await self._repos.accounts.require(account_id)
            if account_id not in self._sessions:
                raise Conflict("connect the account before making it active", code="account_not_connected")
            current = self.active_account_id
            if current is not None and current != account_id:
                refusals = await self._refusals(current)
                if refusals:
                    raise Conflict(
                        "cannot switch the active account: " + "; ".join(refusals), code="switch_refused",
                        details={"reasons": refusals},
                    )  # fmt: skip
            await self._set_active_id(account_id)
        return await self.get(account_id)

    async def _set_active_id(self, account_id: str | None) -> None:
        previous = self.active_account_id
        if previous == account_id:
            return
        self.active_account_id = account_id
        if account_id is None:
            await self._repos.state.delete(ACTIVE_ACCOUNT_KEY)
        else:
            await self._repos.state.set(ACTIVE_ACCOUNT_KEY, {"id": account_id})
        await self._events.publish(ActiveAccountChanged(previous=previous, current=account_id))

    # ------------------------------------------------------------------------------------------ rules ledger
    async def rules_overview(self, account_id: str) -> RulesOverview:
        account = await self._repos.accounts.require(account_id)
        versions = await self._repos.rules.for_account(account_id)
        now = self._clock.now()
        today = await self._repos.risk.today(account_id, now)
        resolution = resolve_rules(versions, today.day_anchor_starts_at_utc, account.rules)
        views = [
            RuleVersionView.model_validate(
                {
                    **v.model_dump(),
                    "status": version_status(v, resolution),
                    "cancellable": cancel_outcome(v) is CancelOutcome.CANCELLED,
                }
            )
            for v in sorted(versions, key=lambda v: v.requested_at, reverse=True)
        ]
        return RulesOverview(
            account_id=account_id,
            resolution=resolution,
            versions=views,
            guard=await self._guard(now),
            evaluated_at=now,
        )

    async def _guard(self, now: datetime) -> GuardDecision:
        """The anti-tilt answer, from what the core sees at this instant: every account's session, the live link."""
        sessions = await self._repos.rules.session_facts(now)
        link = anti_tilt.LiveLink(
            connected=bool(self._sessions),
            account_id=self.active_account_id if self._sessions else None,
            open_positions=self._open_positions(),
        )
        return anti_tilt.decide(link, sessions)

    async def request_rules(self, account_id: str, rules: AccountRules) -> RuleVersion:
        """Append a version. Applied at once only when no session is in progress anywhere (anti-tilt, ADR 0007)."""
        await self._repos.accounts.require(account_id)
        now = self._clock.now()
        decision = await self._guard(now)
        version = await self._repos.rules.append(new_version(account_id, rules, decision, now))
        await self._events.publish(
            AccountRulesChanged(
                account_id=account_id, version_id=version.version_id, deferred=version.deferred,
                reasons=version.deferral_reasons,
            )
        )  # fmt: skip
        return version

    async def cancel_rules(self, version_id: str) -> CancelOutcome:
        version = await self._repos.rules.get(version_id)
        outcome = await self._repos.rules.try_cancel(version_id, self._clock.now())
        if outcome is CancelOutcome.NOT_FOUND:
            raise NotFound(f"unknown rule version {version_id!r}", code="rule_version_not_found")
        if outcome is not CancelOutcome.CANCELLED:
            raise ValidationFailed(f"the change cannot be withdrawn: {outcome.value}", code=f"cancel_{outcome.value}")
        if version is not None:
            await self._events.publish(
                AccountRulesChanged(account_id=version.account_id, version_id=version_id, deferred=True, reasons=[])
            )
        return outcome
