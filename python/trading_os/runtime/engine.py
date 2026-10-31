"""The engine: the core's life cycle — what starts, in which order, what runs every few seconds, and how it stops.

Start, in this order and for these reasons:

1. the database opens (and, when asked, the schema is brought up to date — additive migrations only, under an advisory lock);
2. the accounts load, then the autonomy service (always OFF — except a halt, which stays), the supervisor (open incidents) and
   the news calendar (published from its cache before any network attempt);
3. **commands in flight are put out of harm's way** (``execution.recover``) *before* the agent socket opens: an order that
   might have reached the broker becomes UNKNOWN and is never replayed, and no late reply can race the recovery;
4. the agent socket opens; then the jobs begin.

Stop is the reverse. A graceful stop also steps the automatic modes down to OBSERVE so the record says the core went away on
purpose — the execution agent's dead-man switch would refuse orders within 30 s anyway, and the stops sit at the broker.

The jobs are the cadences of ``docs/architecture`` § 2–3: positions every 2 s, quotes every second, bars, the risk cycle,
the execution sweep, reconciliation, the autonomy duty, the supervisor, the heartbeat, the news refresh. Each is isolated and
measured by the scheduler; the supervisor judges the core from those measures.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Awaitable, Callable

from trading_os.app.container import Container
from trading_os.domain.autonomy.state import AUTOMATIC_MODES, AutonomyMode
from trading_os.domain.events import AccountDisconnected
from trading_os.infrastructure.database.migrate import migrate
from trading_os.runtime.scheduler import Job
from trading_os.services.news import REFRESH_INTERVAL
from trading_os.shared.errors import TradingOsError

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, container: Container, *, migrate_url: str | None = None) -> None:
        """``migrate_url``: when given, pending migrations are applied before anything else (``serve`` does; tests that
        hand in an already-migrated database do not)."""
        self._c = container
        self._migrate_url = migrate_url
        self.running = False
        self._prepared = False

    # ------------------------------------------------------------------------------------------ start
    async def prepare(self) -> None:
        """Everything except the periodic jobs: the state is loaded, recovered, and the agent socket is open. Tests (and the
        cockpit's first paint) can drive the cycles by hand from here; ``start`` adds the clock."""
        c = self._c
        if self._prepared:
            return
        if self._migrate_url is not None:
            applied = await migrate(self._migrate_url)
            if applied:
                logger.info("database migrations applied: %s", ", ".join(applied))
        await c.db.open()

        c.risk.subscribe()
        c.journal.subscribe()
        c.strategy.subscribe()
        c.supervisor.subscribe()
        c.events.subscribe(AccountDisconnected, self._forget_account)

        await c.accounts.start(initial_active=c.settings.active_account_id)
        await c.autonomy.start()
        await c.supervisor.start()
        await c.news.start()
        recovered = await c.execution.recover()
        if recovered:
            logger.warning("%d command(s) left in flight by the previous run were put out of harm's way", recovered)
        if c.ea_server is not None:
            port = await c.ea_server.start()
            logger.info("execution-agent link listening on %s:%d", c.settings.ea_link_host, port)
        self._prepared = True

    async def start(self) -> None:
        if self.running:
            return
        await self.prepare()
        self._register_jobs()
        await self._c.scheduler.start()
        self.running = True
        logger.info("core started (ceiling %s)", self._c.settings.trading_mode.value)

    # ------------------------------------------------------------------------------------------ stop
    async def stop(self) -> None:
        c = self._c
        if not self._prepared:
            return
        self.running = False
        self._prepared = False
        await c.scheduler.stop()
        if c.autonomy.mode in AUTOMATIC_MODES:
            with contextlib.suppress(TradingOsError):
                await c.autonomy.disarm(AutonomyMode.OBSERVE, reason="the core is shutting down", actor="system")
        if c.ea_server is not None:
            await c.ea_server.stop()
        await c.tick_writer.flush()
        await c.accounts.stop()
        await c.news.close()
        await c.db.close()
        logger.info("core stopped")

    # ------------------------------------------------------------------------------------------ internals
    async def _forget_account(self, event: AccountDisconnected) -> None:
        """A link that is gone takes its caches with it: a quote or a position from before must not outlive the connection."""
        if event.account_id is None:
            return
        c = self._c
        c.positions.forget(event.account_id)
        c.market.forget(event.account_id)
        c.risk.forget(event.account_id)
        c.reconciliation.forget(event.account_id)

    def _each(self, work: Callable[[str], Awaitable[object]]) -> Job:
        """Run ``work`` for every connected account. One account failing never skips the others; the first failure is
        re-raised afterwards so the scheduler still counts it."""

        async def job() -> None:
            failure: Exception | None = None
            for account_id in list(self._c.accounts.connected_ids()):
                try:
                    await work(account_id)
                except Exception as error:
                    failure = failure or error
            if failure is not None:
                raise failure

        return job

    @staticmethod
    def _once(work: Callable[[], Awaitable[object]]) -> Job:
        async def job() -> None:
            await work()

        return job

    def _register_jobs(self) -> None:
        c, s = self._c, self._c.settings
        add = c.scheduler.add
        add("heartbeat", c.heartbeat.beat, interval_s=s.heartbeat_interval_s)
        add(
            "positions",
            self._each(c.positions.poll),
            interval_s=s.positions_poll_interval_s,
            timeout_s=30,
            critical=True,
        )
        add("ticks", self._each(c.market.poll_ticks), interval_s=s.tick_poll_interval_s, timeout_s=30)
        add("candles", self._each(c.market.poll_candles), interval_s=5.0, timeout_s=30)
        add("risk", self._each(c.risk.evaluate), interval_s=s.positions_poll_interval_s, timeout_s=30, critical=True)
        add("strategy", self._once(c.strategy.run_pending), interval_s=5.0, timeout_s=60)
        add("execution", self._once(c.execution.sweep), interval_s=2.0, timeout_s=30, critical=True)
        add(
            "reconciliation", self._once(c.reconciliation.reconcile_connected), interval_s=15.0, timeout_s=90,
            critical=True,
        )  # fmt: skip
        add("autonomy", c.autonomy.tick, interval_s=2.0, timeout_s=30)
        add("supervisor", c.supervisor.tick, interval_s=s.supervisor_interval_s, timeout_s=30, critical=True)
        add("tick_writer", c.tick_writer.flush, interval_s=1.0, timeout_s=15)
        add(
            "news", self._once(c.news.refresh), interval_s=REFRESH_INTERVAL.total_seconds(), timeout_s=120,
            initial_delay_s=5.0,
        )  # fmt: skip


__all__ = ["Engine"]
