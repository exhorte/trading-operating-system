"""Accounts: the registry, the connections, the single active account, the trading switch, and the versioned rules.

* An account is *configuration* (``Account``): no secret. A connection is *runtime* (``AccountSession``): one MT5 client per
  connected account, one terminal each. A password is handed to ``connect`` and forgotten — or read from the
  ``CredentialStore`` the user opted into — and never stored on the session.
* **Exactly one account is active.** Only it receives automatic commands; a human command names its ``accountId``
  explicitly and must match the account really attached (ADR 0010).
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
from datetime import datetime
from typing import Protocol

from pydantic import Field, SecretStr

from trading_os.domain.accounts import anti_tilt
from trading_os.domain.accounts.anti_tilt import GuardDecision
from trading_os.domain.accounts.models import (
    Account,
    AccountRules,
    AccountStatus,
    AccountType,
    Environment,
    FtmoChallenge,
    Provider,
)
from trading_os.domain.accounts.profiles import ProfileParams, default_rules, provider_profile
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
from trading_os.infrastructure.mt5.client import Mt5AccountInfo, Mt5Client
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.infrastructure.security.credentials import CredentialStore
from trading_os.shared.errors import Conflict, NotFound, TradingOsError, Unavailable, ValidationFailed
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

ACTIVE_ACCOUNT_KEY = "active_account"

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
        return self._view(account.with_rules(resolution.rules))

    async def _resolution(self, account: Account) -> RuleResolution:
        versions = await self._repos.rules.for_account(account.id)
        today = await self._repos.risk.today(account.id, self._clock.now())
        return resolve_rules(versions, today.day_anchor_starts_at_utc, account.rules)

    # ------------------------------------------------------------------------------------------ registry
    async def create(self, spec: AccountCreate) -> Account:
        profile = provider_profile(spec.provider)
        rules = default_rules(
            spec.provider,
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

    # ------------------------------------------------------------------------------------------ connections
    async def connect(self, account_id: str, password: SecretStr | None = None) -> Account:
        async with self._lock:
            account = await self._repos.accounts.require(account_id)
            if account_id in self._sessions:
                return self._view(account)
            clash = self._terminal_clash(account)
            if clash is not None:
                raise Conflict(
                    f"account {clash} is connected on the same terminal: disconnect it first", code="terminal_in_use"
                )
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
        if self.active_account_id is None:
            await self._set_active_id(account_id)
        return self._view(account)

    def _terminal_clash(self, account: Account) -> str | None:
        for other in self._sessions.values():
            if other.account.id != account.id and other.account.terminal_path == account.terminal_path:
                return other.account.id
        return None

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
