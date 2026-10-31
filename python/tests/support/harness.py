"""A small in-process core for service tests: real PostgreSQL (the ``db`` fixture), simulated MT5 terminals, a clock the
test moves by hand, and a recorder of every event published."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from tests.support.builders import NOW
from trading_os.domain.accounts.models import Account
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.mt5.client import Mt5Client
from trading_os.infrastructure.mt5.fake import FakeAccount, FakeMt5
from trading_os.infrastructure.mt5.transport import InProcessTransport
from trading_os.infrastructure.security.credentials import CredentialStore, NullCredentialStore
from trading_os.shared.events.base import Event
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import ManualClock

E = TypeVar("E", bound=Event)


class Recorder:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def __call__(self, event: Event) -> None:
        self.events.append(event)

    def of(self, kind: type[E]) -> list[E]:
        return [e for e in self.events if isinstance(e, kind)]

    def types(self) -> list[str]:
        return [e.wire_type for e in self.events]

    def clear(self) -> None:
        self.events.clear()


@dataclass
class Harness:
    db: Database
    repos: Repositories
    events: EventDispatcher
    recorder: Recorder
    clock: ManualClock
    credentials: CredentialStore = field(default_factory=NullCredentialStore)
    terminals: dict[str | None, FakeMt5] = field(default_factory=dict)
    server_offset_minutes: int = 0  # offset of the simulated broker clock from UTC

    @classmethod
    def create(cls, db: Database) -> Harness:
        events = EventDispatcher()
        recorder = Recorder()
        events.subscribe_all(recorder)
        clock = ManualClock(NOW)
        return cls(db=db, repos=Repositories.create(db), events=events, recorder=recorder, clock=clock)

    def terminal(self, account: Account) -> FakeMt5:
        """The simulated terminal of the account's ``terminal_path`` (one per path), aware of the account's login."""
        terminal = self.terminals.get(account.terminal_path)
        if terminal is None:
            terminal = FakeMt5.for_accounts(
                [],
                suffix=account.symbol_suffix,
                server_offset_minutes=self.server_offset_minutes,
                clock=lambda: self.clock.now().timestamp(),
            )
            self.terminals[account.terminal_path] = terminal
        if account.login not in terminal.accounts:
            terminal.accounts[account.login] = FakeAccount(
                login=account.login, server=account.server, password=f"pw-{account.login}", currency=account.currency
            )
        return terminal

    def mt5_factory(self, account: Account) -> Mt5Client:
        return Mt5Client(InProcessTransport(self.terminal(account)), account_id=account.id, clock=self.clock)
