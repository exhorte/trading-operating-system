"""The container: the one place where the object graph is assembled (and the only place that knows every service).

Nothing here performs I/O — ``build_container`` only wires; the engine opens the database, starts the sockets and the jobs.
Everything that talks to the outside world can be replaced by the caller (database, terminal factory, execution-agent
link, FRED client, clock), which is how the whole core runs in tests against a simulated terminal and a scripted agent.

The wiring has two knots, both resolved here and nowhere else:

* the execution service needs the agent link to send, and the link needs the execution service to report: the server is
  built first with no handler and handed one afterwards;
* the autonomy service, the Risk Engine and the supervisor each read the others (the mode, the halt, the SAFE reasons, the
  readiness facts): the services are built, then connected with ``wire``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trading_os.app.audit import AuditTrail
from trading_os.app.config import Settings
from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.mt5.client import Mt5Client
from trading_os.infrastructure.mt5.ea_link import EaLinkServer, NullHandler
from trading_os.infrastructure.mt5.transport import SubprocessTransport
from trading_os.infrastructure.news.fred import FredCalendarClient
from trading_os.infrastructure.security.credentials import CredentialStore, build_credential_store
from trading_os.runtime.heartbeat import Heartbeat
from trading_os.runtime.scheduler import Scheduler
from trading_os.runtime.supervisor import Supervisor
from trading_os.services.accounts import AccountService, Mt5Factory
from trading_os.services.autonomy import AutonomyService
from trading_os.services.execution import AgentLinkPort, ExecutionService
from trading_os.services.gateways import EaLinkGateway, ObserveGateway, PaperGateway
from trading_os.services.journal import JournalService
from trading_os.services.market_data import MarketDataService, TickWriter
from trading_os.services.news import CalendarClient, NewsService
from trading_os.services.positions import PositionService
from trading_os.services.readiness import AccountCheck, ReadinessCollector
from trading_os.services.reconciliation import ReconciliationService
from trading_os.services.risk import RiskService
from trading_os.services.strategy import StrategyService
from trading_os.shared.errors import ValidationFailed
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock, SystemClock


class AgentLink(AgentLinkPort, Protocol):
    """What the core needs of the execution-agent link: ``EaLinkServer`` in production, a scripted double in tests."""

    async def send_line(self, login: str, line: bytes) -> bool: ...


@dataclass
class Container:
    settings: Settings
    clock: Clock
    db: Database
    repos: Repositories
    events: EventDispatcher
    audit: AuditTrail
    credentials: CredentialStore
    accounts: AccountService
    tick_writer: TickWriter
    market: MarketDataService
    positions: PositionService
    news: NewsService
    autonomy: AutonomyService
    agent_link: AgentLink
    ea_server: EaLinkServer | None  # None when the caller supplied its own link
    execution: ExecutionService
    risk: RiskService
    reconciliation: ReconciliationService
    journal: JournalService
    strategy: StrategyService
    scheduler: Scheduler
    heartbeat: Heartbeat
    supervisor: Supervisor
    readiness: ReadinessCollector


def default_mt5_factory(settings: Settings, clock: Clock) -> Mt5Factory:
    """One read worker (a child process) per account. ``MT5_ENABLED=false`` serves the simulated terminal instead."""
    backend = "real" if settings.mt5_enabled else "fake"

    def factory(account: Account) -> Mt5Client:
        return Mt5Client(SubprocessTransport(backend=backend), account_id=account.id, clock=clock)

    return factory


def build_container(
    settings: Settings,
    *,
    clock: Clock | None = None,
    db: Database | None = None,
    mt5_factory: Mt5Factory | None = None,
    agent_link: AgentLink | None = None,
    news_client: CalendarClient | None = None,
    credentials: CredentialStore | None = None,
    strategy_check: AccountCheck | None = None,
    exits_check: AccountCheck | None = None,
) -> Container:
    clock = clock or SystemClock()
    if db is None:
        if settings.database_url is None:
            raise ValidationFailed(
                "DATABASE_URL is not configured (scripts/start.ps1 writes it to .env)", code="database_not_configured"
            )
        db = Database(settings.database_url.get_secret_value())
    repos = Repositories.create(db)
    events = EventDispatcher()
    audit = AuditTrail(repos)
    events.subscribe_all(audit)

    credentials = credentials or build_credential_store(settings.credential_store)
    accounts = AccountService(
        repos=repos, events=events, clock=clock, credentials=credentials,
        mt5_factory=mt5_factory or default_mt5_factory(settings, clock),
    )  # fmt: skip
    tick_writer = TickWriter(repos.market)
    market = MarketDataService(
        accounts=accounts, repos=repos, events=events, clock=clock, tick_writer=tick_writer,
        backfill_bars=settings.market_backfill_bars,
    )  # fmt: skip
    positions = PositionService(accounts=accounts, repos=repos, events=events, clock=clock, market=market)
    accounts.set_open_positions_provider(positions.total_open_count)
    accounts.add_guard(positions.guard)

    fred_key = settings.fred_api_key
    if news_client is None and fred_key is not None and fred_key.get_secret_value():
        news_client = FredCalendarClient(fred_key)
    news = NewsService(repos=repos, events=events, clock=clock, client=news_client)

    # TRADING_MODE is the ceiling of the whole process; the autonomy service starts OFF and only a human climbs.
    autonomy = AutonomyService(
        repos=repos, events=events, clock=clock, accounts=accounts, ceiling=AutonomyMode(settings.trading_mode.value)
    )

    ea_server: EaLinkServer | None = None
    if agent_link is None:
        token = settings.trading_os_agent_token
        ea_server = EaLinkServer(
            host=settings.ea_link_host, port=settings.ea_link_port,
            token=token.get_secret_value() if token else None, handler=NullHandler(), clock=clock,
            stale_after=settings.ea_silent_after_s, ping_interval=settings.ea_ping_interval_s,
        )  # fmt: skip
        agent_link = ea_server
    ea_gateway = EaLinkGateway(agent_link, clock)
    execution = ExecutionService(
        accounts=accounts, repos=repos, events=events, clock=clock, link=agent_link,
        gateways={
            ExecutionRoute.NONE: ObserveGateway(),
            ExecutionRoute.PAPER: PaperGateway(market),
            ExecutionRoute.CONFIRM: ea_gateway,
            ExecutionRoute.AUTOMATIC: ea_gateway,
        },
        effective_mode=autonomy.effective_mode, halted=autonomy.halted,
    )  # fmt: skip
    if ea_server is not None:
        ea_server.set_handler(execution)
    accounts.add_guard(execution.guard)

    risk = RiskService(
        accounts=accounts, positions=positions, market=market, repos=repos, events=events, clock=clock,
        calendar=news, agents=execution,
    )  # fmt: skip
    positions.set_enricher(risk.enrich)
    reconciliation = ReconciliationService(
        accounts=accounts, execution=execution, repos=repos, events=events, clock=clock
    )
    journal = JournalService(
        repos=repos, events=events, clock=clock, accounts=accounts, positions=positions, market=market
    )

    strategy = StrategyService(
        accounts=accounts, market=market, news=news, risk=risk, execution=execution, autonomy=autonomy, repos=repos,
        events=events, clock=clock,
    )  # fmt: skip

    scheduler = Scheduler(clock)
    heartbeat = Heartbeat(events=events, clock=clock)
    supervisor = Supervisor(
        accounts=accounts, positions=positions, market=market, risk=risk, execution=execution,
        reconciliation=reconciliation, autonomy=autonomy, db=db, scheduler=scheduler, repos=repos, events=events,
        clock=clock,
    )  # fmt: skip
    readiness = ReadinessCollector(
        accounts=accounts, positions=positions, market=market, risk=risk, execution=execution,
        reconciliation=reconciliation, supervisor=supervisor, scheduler=scheduler, heartbeat=heartbeat, db=db,
        clock=clock, strategy=strategy_check or strategy.readiness, exits=exits_check,
    )  # fmt: skip

    autonomy.wire(readiness=readiness, halt_agents=execution.halt_agents)
    risk.wire(
        autonomy_permits_entries=autonomy.permits_entries, halted=autonomy.halted, degraded=supervisor.degraded_for
    )

    return Container(
        settings=settings, clock=clock, db=db, repos=repos, events=events, audit=audit, credentials=credentials,
        accounts=accounts, tick_writer=tick_writer, market=market, positions=positions, news=news, autonomy=autonomy,
        agent_link=agent_link, ea_server=ea_server, execution=execution, risk=risk, reconciliation=reconciliation,
        journal=journal, strategy=strategy, scheduler=scheduler, heartbeat=heartbeat, supervisor=supervisor,
        readiness=readiness,
    )  # fmt: skip
