"""A whole core in a test: the real container and engine, a real database, simulated terminals, a scripted execution agent
and a clock the test moves. The periodic jobs are not started — ``Core.cycle`` runs one pass of each, in the order the engine
runs them, so a scenario is deterministic and a fault can be introduced between two cycles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import SecretStr

from tests.support.harness import Harness, Recorder
from tests.unit.services.test_accounts_service import exness
from trading_os.app.config import Settings, TradingMode
from trading_os.app.container import Container, build_container
from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.readiness import Fact
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.agent import AgentStatus
from trading_os.infrastructure.mt5.fake import FakeMt5
from trading_os.infrastructure.mt5.wire import AgentHeartbeat
from trading_os.infrastructure.security.credentials import CredentialStore
from trading_os.runtime.engine import Engine
from trading_os.shared.time import to_epoch_ms

AGENT_MAGIC = 7001


@dataclass
class ScriptedLink:
    """The execution agent as the core sees it: who is registered, what was said to them, whether a write succeeds."""

    statuses: dict[str, AgentStatus] = field(default_factory=dict)
    halts: list[tuple[str, str]] = field(default_factory=list)
    lines: list[tuple[str, bytes]] = field(default_factory=list)
    deliver: bool = True

    def status(self, login: str) -> AgentStatus | None:
        return self.statuses.get(login)

    def is_connected(self, login: str | None = None) -> bool:
        return bool(self.statuses) if login is None else login in self.statuses

    def registered_logins(self) -> list[str]:
        return sorted(self.statuses)

    async def send_halt(self, login: str, reason: str) -> bool:
        status = self.statuses.get(login)
        if status is None or not status.can("halt"):
            return False
        self.halts.append((login, reason))
        self.statuses[login] = status.model_copy(update={"halted": True})  # the agent reports it in its next heartbeat
        return True

    async def send_line(self, login: str, line: bytes) -> bool:
        if not self.deliver or login not in self.statuses:
            return False
        self.lines.append((login, line))
        return True


class MemoryCredentialStore:
    """A vault that lives in the test: ``put``/``get``/``has``/``delete`` like the real ones, and a ``secrets`` dict to peek at."""

    name = "memory"

    def __init__(self) -> None:
        self.secrets: dict[str, SecretStr] = {}

    async def get(self, account_id: str) -> SecretStr | None:
        return self.secrets.get(account_id)

    async def put(self, account_id: str, password: SecretStr) -> None:
        self.secrets[account_id] = password

    async def delete(self, account_id: str) -> None:
        self.secrets.pop(account_id, None)

    async def has(self, account_id: str) -> bool:
        return account_id in self.secrets


def green(detail: str = "provided by the test") -> Fact:
    return Fact(ok=True, detail=detail)


@dataclass
class Core:
    h: Harness
    c: Container
    engine: Engine
    link: ScriptedLink
    recorder: Recorder
    account: Account | None = None

    # ------------------------------------------------------------------------------------------ building a scenario
    async def add_account(
        self, *, max_mode: AutonomyMode = AutonomyMode.AUTONOMOUS, configured: bool = True, connect: bool = True,
        login: int = 1_000_001,
    ) -> Account:  # fmt: skip
        created = await self.c.accounts.create(exness(login=login))
        if connect:
            await self.c.accounts.connect(created.id)
        rules = created.rules
        await self.c.accounts.request_rules(
            created.id,
            rules.model_copy(
                update={
                    "execution_profile": rules.execution_profile.model_copy(update={"max_mode": max_mode}),
                    "risk_profile": rules.risk_profile.model_copy(update={"configured": configured}),
                }
            ),
        )  # fmt: skip
        self.h.clock.advance(seconds=1)  # the next rules version never shares an instant with this one
        self.account = await self.c.accounts.effective(created.id)
        return self.account

    @property
    def terminal(self) -> FakeMt5:
        assert self.account is not None
        return self.h.terminal(self.account)

    @property
    def login(self) -> str:
        assert self.account is not None
        return str(self.account.login)

    async def register_agent(
        self, *, capabilities: tuple[str, ...] = ("ping", "halt"), beat: bool = True
    ) -> AgentStatus:
        status = AgentStatus(
            account_login=self.login, agent_id=f"mt5-execution-agent-{AGENT_MAGIC}", identity="ok", tradable=True,
            halted=False, capabilities=list(capabilities),
        )  # fmt: skip
        self.link.statuses[self.login] = status
        await self.c.execution.on_registered(status)
        if beat:
            await self.beat_agent()
        return status

    async def beat_agent(self) -> None:
        await self.c.execution.on_heartbeat(
            self.login,
            AgentHeartbeat(account_id=self.login, agent_id="agent", time=to_epoch_ms(self.h.clock.now())),
        )

    # ------------------------------------------------------------------------------------------ driving the clock
    async def cycle(self, *, agent_beats: bool = True) -> None:
        """One pass of every job, in the order of ``Engine._register_jobs`` (minus the wall clock)."""
        c = self.c
        if agent_beats and self.account is not None and self.login in self.link.statuses:
            await self.beat_agent()
        await c.heartbeat.beat()
        for account_id in list(c.accounts.connected_ids()):
            await c.positions.poll(account_id)
            await c.market.poll_ticks(account_id)
            await c.risk.evaluate(account_id)
        await c.execution.sweep()
        await c.reconciliation.reconcile_connected()
        await c.autonomy.tick()
        await c.supervisor.tick()

    async def climb(self, top: AutonomyMode) -> None:
        """Walk the autonomy ladder one rung at a time up to ``top`` (the readiness must be green for the automatic rungs)."""
        order = (
            AutonomyMode.OBSERVE, AutonomyMode.PAPER, AutonomyMode.CONFIRM, AutonomyMode.ARMED, AutonomyMode.AUTONOMOUS,
        )  # fmt: skip
        for mode in order:
            await self.c.autonomy.arm(mode)
            if mode is top:
                return


async def make_core(
    h: Harness,
    *,
    ceiling: AutonomyMode = AutonomyMode.AUTONOMOUS,
    providers: bool = True,
    settings: dict[str, Any] | None = None,
    credentials: CredentialStore | None = None,
) -> Core:
    """``providers=False``: no strategy and no exit management are registered — the readiness says so (as it does today)."""
    link = ScriptedLink()
    options: dict[str, Any] = {"trading_mode": TradingMode(ceiling.value), "market_backfill_bars": 50}
    options.update(settings or {})
    container = build_container(
        Settings(_env_file=None, **options),
        clock=h.clock, db=h.db, mt5_factory=h.mt5_factory, agent_link=link, credentials=credentials,
        strategy_check=(lambda account: green("test strategy")) if providers else None,
        exits_check=(lambda account: green("test exits")) if providers else None,
    )  # fmt: skip
    recorder = Recorder()
    container.events.subscribe_all(recorder)
    engine = Engine(container)
    await engine.prepare()
    return Core(h=h, c=container, engine=engine, link=link, recorder=recorder)


async def make_ready_core(
    h: Harness, *, top: AutonomyMode = AutonomyMode.OBSERVE, credentials: CredentialStore | None = None
) -> Core:
    """A core with a connected account, an agent, a few cycles behind it — and the autonomy ladder climbed to ``top``."""
    core = await make_core(h, credentials=credentials)
    await core.add_account()
    await core.register_agent()
    for _ in range(2):
        core.h.clock.advance(seconds=2)
        await core.cycle()
    await core.climb(top)
    return core
