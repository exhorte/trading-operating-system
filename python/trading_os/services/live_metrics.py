"""Live measurements (ADR 0035, L1): the quotes, the agent link and the commands as they really were. Read-only.

Two sources, never mixed up:

* **stored** — the ticks table (the spread and the rate of the quotes the core saw) and the command rows (their
  timestamps, states and broker return codes). They survive a restart and answer for any past window, with or without a
  running core: the CLI report reads only these (``stored_quotes``).
* **seen since the core started** — how late each new quote reached the core, kept in a bounded in-memory window from the
  ``MarketTickReceived`` events. A restart empties it, and the report says so by showing ``n = 0``.

Nothing is written, nothing is sent to the terminal or the agent, nothing is estimated: what cannot be measured is
``None`` / an empty distribution and is named in ``not_measured``.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from datetime import datetime, timedelta

from trading_os.domain.events import MarketTickReceived
from trading_os.domain.market.hours import is_market_open
from trading_os.domain.market.symbols import to_canonical
from trading_os.domain.telemetry.live_metrics import (
    CAVEATS,
    MAX_WINDOW_MINUTES,
    AgentLinkMetrics,
    CommandMetrics,
    Distribution,
    LiveMetrics,
    QuoteMetrics,
    command_metrics,
    distribution,
    not_measured,
    ticks_per_minute,
)
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.accounts import AccountService
from trading_os.services.execution import ExecutionService
from trading_os.services.market_data import MarketDataService
from trading_os.shared.errors import ValidationFailed
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

KEEP_LAGS = 5_000  # per symbol: about an hour and a half at one new quote a second


async def stored_quotes(
    repos: Repositories, symbols: Sequence[str], start: datetime, end: datetime
) -> list[QuoteMetrics]:
    """The spread and the tick rate of each symbol over ``[start, end)``, from the stored ticks alone."""
    quotes: list[QuoteMetrics] = []
    for symbol in symbols:
        row = await repos.market.spread_summary(symbol, start, end)
        ticks = int(row["n"])
        span = (row["last_ts"] - row["first_ts"]).total_seconds() if ticks else None
        spread = (
            Distribution(
                n=ticks,
                min=round(row["low"], 10),
                median=round(row["median"], 10),
                p95=round(row["p95"], 10),
                max=round(row["high"], 10),
            )
            if ticks
            else Distribution(n=0)
        )
        quotes.append(
            QuoteMetrics(
                symbol=symbol,
                ticks=ticks,
                span_s=span,
                ticks_per_minute=ticks_per_minute(ticks, span),
                spread=spread,
                receipt_lag_s=Distribution(n=0),
            )
        )
    return quotes


async def stored_commands(
    repos: Repositories, account_id: str, start: datetime, end: datetime | None = None
) -> CommandMetrics:
    """The commands created in ``[start, end)`` (``end`` open: up to now)."""
    commands = await repos.execution.created_since(account_id, start)
    return command_metrics([c for c in commands if end is None or c.created_at < end])


class LiveMetricsService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        market: MarketDataService,
        execution: ExecutionService,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
    ) -> None:
        self._accounts = accounts
        self._market = market
        self._execution = execution
        self._repos = repos
        self._events = events
        self._clock = clock
        self._lags: dict[tuple[str, str], deque[tuple[datetime, float]]] = defaultdict(lambda: deque(maxlen=KEEP_LAGS))

    def subscribe(self) -> None:
        self._events.subscribe(MarketTickReceived, self._on_tick)

    async def _on_tick(self, event: MarketTickReceived) -> None:
        if event.account_id is None:
            return
        seen = self._clock.now()
        # Kept as it is, a negative value included: a quote "from the future" is a clock fault the report must show.
        self._lags[(event.account_id, event.tick.symbol)].append((seen, (seen - event.tick.time).total_seconds()))

    async def snapshot(self, account_id: str, minutes: int) -> LiveMetrics:
        if not 1 <= minutes <= MAX_WINDOW_MINUTES:
            raise ValidationFailed(f"the window is 1 to {MAX_WINDOW_MINUTES} minutes", code="bad_window")
        now = self._clock.now()
        start = now - timedelta(minutes=minutes)
        symbols = self._market.watchlist(account_id)

        quotes: list[QuoteMetrics] = []
        for stored in await stored_quotes(self._repos, symbols, start, now + timedelta(seconds=1)):
            tick = self._market.tick(account_id, stored.symbol)
            lags = [lag for seen, lag in self._lags.get((account_id, stored.symbol), ()) if seen >= start]
            quotes.append(
                stored.model_copy(
                    update={
                        "receipt_lag_s": distribution(lags, digits=3),
                        "last_tick_age_s": round((now - tick.time).total_seconds(), 3) if tick else None,
                        "market_open": is_market_open(to_canonical(stored.symbol), now),
                    }
                )
            )

        session = self._accounts.session(account_id)
        login = str(session.account.login) if session is not None else None
        beat = self._execution.last_heartbeat(login) if login is not None else None
        agent = AgentLinkMetrics(
            connected=login is not None and self._execution.agent_status(login) is not None,
            last_heartbeat_age_s=round((now - beat).total_seconds(), 3) if beat is not None else None,
        )

        commands = await stored_commands(self._repos, account_id, start)
        return LiveMetrics(
            observed_at=now,
            account_id=account_id,
            window_minutes=minutes,
            quotes=quotes,
            agent=agent,
            commands=commands,
            caveats=list(CAVEATS),
            not_measured=not_measured(quotes, agent, commands, terminal_connected=session is not None),
        )
