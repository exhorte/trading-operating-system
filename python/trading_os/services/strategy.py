"""StrategyService — runs S01 on the closed candles of the active account, records what it saw, and hands what it proposes to the Risk
Engine. It decides neither the risk nor the order (ADR 0007): Strategy → TradeIntent → Risk → Execution.

* **It measures.** Every closed M1 candle of a watched symbol is one evaluation, recorded whether it proposed or not — the stage where
  the sequence stopped is the measurement of ADR 0011 (« POURQUOI la machine n'a rien proposé »). A rolling evaluation re-detects the
  same real setup on several consecutive candles; the displacement's own timestamp keys the row, so that is one row, not a stream.
* **It acts only as far as the mode lets it.** OFF and HALTED evaluate nothing. From OBSERVE up, a fresh proposal becomes a
  ``TradeIntent`` (persisted first) and the Risk Engine is asked for a decision (persisted too) — OBSERVE records that and sends
  nothing, the Risk Engine itself refuses entries there. Only an *approved* decision goes on to the execution engine, and the engine
  decides what the mode does with it (paper fill, wait for a human, send). A setup is handled **once**: the intent's id is the
  proposal's id, so a later candle that re-detects it — or a mode raised afterwards — never resurrects a stale setup.
* **It never invents.** No spread, no specification, a missing timeframe or a feed that fails: the cycle is skipped and nothing is
  recorded (the original's behaviour), the failure is kept for the readiness check instead of being hidden.

S01's entry is a **limit** at the CE of the point of interest. Since ADR 0023 the core carries limit orders: PAPER simulates them, and a
real agent receives one only if it announces the ``limit`` capability (agent 1.11 does not — the hand-off then ends in a recorded
``AGENT_CAPABILITY_MISSING`` rejection, which is the truth about the system and is shown as such).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.readiness import Fact
from trading_os.domain.events import (
    CandleClosed,
    StrategyEvaluationCompleted,
    StrategyEvaluationStarted,
    TradeIntentCreated,
    TradeRejected,
)
from trading_os.domain.execution.commands import CommandKind, ExecutionRequest
from trading_os.domain.market.hours import is_market_open
from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import DEFAULT_SESSION_WINDOWS
from trading_os.domain.market.symbols import to_broker, to_canonical
from trading_os.domain.primitives import Timeframe
from trading_os.domain.risk.sizing import commission_in_price
from trading_os.domain.strategy.evaluation import StrategyEvaluation
from trading_os.domain.strategy.intent import OrderKind, TradeIntent
from trading_os.domain.strategy.s01 import (
    ProposedOutcome,
    SetupOutcome,
    SetupProposal,
    SetupProposalInput,
    evaluate_setup,
)
from trading_os.domain.strategy.s01.config import S01Config
from trading_os.domain.strategy.s01.preconditions import blocking_precondition
from trading_os.domain.strategy.s01.proposal import S01_VARIANT, Variant
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.services.accounts import AccountService
from trading_os.services.autonomy import AutonomyService
from trading_os.services.execution import ExecutionService
from trading_os.services.market_data import MarketDataService
from trading_os.services.news import NewsService
from trading_os.services.risk import RiskService
from trading_os.shared.errors import TradingOsError, Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

STRATEGY_ID = "S01"
STRATEGY_VERSION = "1"


@dataclass(frozen=True)
class StrategyDefinition:
    """What distinguishes one strategy service from another (ADR 0024): who it is, how it reads the market, how far it may go."""

    strategy_id: str = STRATEGY_ID
    version: str = STRATEGY_VERSION
    variant: Variant = S01_VARIANT
    needs_d1: bool = True  # S01 reads the daily bias on D1; S02 reads it on H1
    acts: bool = True  # False = measure only: evaluations are recorded, nothing goes to the Risk Engine


S01_DEFINITION = StrategyDefinition()
STALE_AFTER = timedelta(
    minutes=10
)  # on an open market, a strategy that has not evaluated for this long is not « valid »


class StrategyService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        market: MarketDataService,
        news: NewsService,
        risk: RiskService,
        execution: ExecutionService,
        autonomy: AutonomyService,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        config: S01Config | None = None,
        definition: StrategyDefinition = S01_DEFINITION,
    ) -> None:
        self.definition = definition
        self._accounts = accounts
        self._market = market
        self._news = news
        self._risk = risk
        self._execution = execution
        self._autonomy = autonomy
        self._repos = repos
        self._events = events
        self._clock = clock
        self.config = config or S01Config()
        self._pending: set[tuple[str, str]] = set()
        self._last_candle: dict[tuple[str, str], datetime] = {}
        self._last_evaluation: dict[str, StrategyEvaluation] = {}
        self._last_evaluated_at: dict[str, datetime] = {}
        self.last_error: str | None = None

    def subscribe(self) -> None:
        """A closed M1 candle of a watched symbol of the active account marks one evaluation as due."""
        self._events.subscribe(CandleClosed, self._on_candle_closed)

    # ------------------------------------------------------------------------------------------ reading
    def last_evaluation(self, account_id: str) -> StrategyEvaluation | None:
        return self._last_evaluation.get(account_id)

    def readiness(self, account: Account) -> Fact:
        """The ``strategy_valid`` fact: the strategy is registered, runs for the active account, and is not failing or silent."""
        name = self.definition.strategy_id
        if account.id != self._accounts.active_account_id:
            return Fact(ok=False, detail=f"{name} runs for the active account only")
        if self.last_error is not None:
            return Fact(ok=False, detail=f"the last evaluation failed: {self.last_error}")
        now = self._clock.now()
        last_at = self._last_evaluated_at.get(account.id)
        symbols = ", ".join(to_broker(s, account.symbol_suffix) for s in self.config.symbols)
        if last_at is None:
            return Fact(ok=False, detail=f"{name} has not evaluated {symbols} since the core started")
        age = now - last_at
        if age > STALE_AFTER and any(is_market_open(s, now) for s in self.config.symbols):
            return Fact(ok=False, detail=f"{name} has been silent for {int(age.total_seconds())}s on an open market")
        last = self._last_evaluation[account.id]
        what = "proposed" if last.status == "proposed" else f"stopped at {last.stage}"
        return Fact(ok=True, detail=f"{name} evaluated {symbols} {int(age.total_seconds())}s ago ({what})")

    # ------------------------------------------------------------------------------------------ scheduling
    def _on_candle_closed(self, event: CandleClosed) -> None:
        if event.account_id is None or event.account_id != self._accounts.active_account_id:
            return
        candle = event.candle
        if candle.timeframe is not Timeframe.M1:
            return
        canonical = to_canonical(candle.symbol)
        if canonical is not None and canonical in self.config.symbols:
            self._pending.add((event.account_id, candle.symbol))

    async def run_pending(self) -> int:
        """Evaluate every symbol whose candle closed since the last call. One failing never skips the others; the first failure is
        re-raised afterwards so the scheduler counts it."""
        done = 0
        failure: Exception | None = None
        for key in sorted(self._pending):
            self._pending.discard(key)
            try:
                if await self.evaluate(*key) is not None:
                    done += 1
            except Exception as error:  # a bug must not stop the other symbols, nor go unseen
                logger.exception("strategy: evaluating %s failed", key)
                self.last_error = f"{type(error).__name__}"
                failure = failure or error
        if failure is not None:
            raise failure
        return done

    # ------------------------------------------------------------------------------------------ one evaluation
    async def evaluate(self, account_id: str, symbol: str) -> StrategyEvaluation | None:
        """One S01 pass on one symbol of the active account. ``None`` when there was nothing to evaluate — not the active account,
        the autonomy OFF or HALTED, a feed that is missing or failing, a candle already evaluated: that is not an outcome and nothing
        is recorded."""
        if account_id != self._accounts.active_account_id or not self._autonomy.state.evaluates_strategies:
            return None
        if self._accounts.session(account_id) is None:
            return None
        account = await self._accounts.effective(account_id)
        try:
            result = await self._decide(account, symbol)
        except (WorkerError, Unavailable) as error:
            self.last_error = error.safe_message if isinstance(error, TradingOsError) else f"MT5 worker: {error.code}"
            logger.warning(
                "strategy: %s on %s could not read its inputs: %s", self.definition.strategy_id, symbol, self.last_error
            )
            return None
        if result is None:
            return None
        candle_at, outcome = result
        self.last_error = None
        evaluation = self._to_evaluation(self.definition.strategy_id, symbol, candle_at, outcome)
        self._last_evaluation[account_id] = evaluation
        self._last_evaluated_at[account_id] = self._clock.now()
        try:
            await self._repos.strategy.record_evaluation(evaluation)
        except Unavailable:
            logger.warning("strategy: evaluation of %s not recorded: database unavailable", symbol)
        await self._events.publish(
            StrategyEvaluationCompleted(
                account_id=account_id, strategy_id=self.definition.strategy_id, symbol=symbol, outcome=evaluation.status,
                stage=evaluation.stage, detail=evaluation.detail, event_at=evaluation.event_at,
            )
        )  # fmt: skip
        if isinstance(outcome, ProposedOutcome) and self.definition.acts:
            await self._hand_over(account, outcome.proposal)
        return evaluation

    async def _closed(self, account_id: str, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        """Closed candles only: a forming bar has no confirmed body, and S01 validates structure « en clôture de corps »."""
        return [c for c in await self._market.recent_candles(account_id, symbol, timeframe, count) if c.closed]

    async def _decide(self, account: Account, symbol: str) -> tuple[datetime, SetupOutcome] | None:
        cfg = self.config
        m1 = await self._closed(account.id, symbol, Timeframe.M1, cfg.m1_bars)
        if not m1:
            return None
        candle_at = m1[-1].open_time
        key = (account.id, symbol)
        if self._last_candle.get(key) == candle_at:
            return None  # this closed candle was evaluated already
        await self._events.publish(
            StrategyEvaluationStarted(account_id=account.id, strategy_id=self.definition.strategy_id, symbol=symbol)
        )
        now = self._clock.now()

        # Pre-conditions: « si une seule manque, il n'y a pas de recherche ». They come from the Risk Engine's own sources.
        policy = account.risk_profile
        status = self._risk.status(account.id)
        blocked = blocking_precondition(
            candle_at,
            releases=self._news.snapshot().usable(now, timedelta(hours=policy.news.calendar_max_age_hours)),
            blackout_minutes=policy.news.blackout_minutes,
            lockout_active=await self._repos.risk.active_lockout(account.id, now) is not None,
            trades_today=status.trades_today if status else None,
            max_trades_per_day=policy.max_trades_per_day,
            windows=cfg.trading_windows,  # the hours of THIS strategy (ADR 0030): S01's are not S02's
        )
        if blocked is not None:
            self._last_candle[key] = candle_at
            return candle_at, blocked

        tick = self._market.tick(account.id, symbol)
        if tick is None:
            return None  # no live spread yet: skip this cycle, nothing is recorded
        h1 = await self._closed(account.id, symbol, Timeframe.H1, cfg.h1_bars)
        h4 = await self._closed(account.id, symbol, Timeframe.H4, cfg.h4_bars)
        d1 = await self._closed(account.id, symbol, Timeframe.D1, cfg.d1_bars)
        if not (h1 and h4 and (d1 or not self.definition.needs_d1)):
            return None  # a timeframe we do not actually have is never evaluated as if we did
        spec = await self._market.require_spec(account.id, symbol)
        limits = account.execution_profile.limits
        cutoff = max(0, len(m1) - cfg.reaction_window_m1_bars)
        map_candles: list[Candle] = []
        if self.definition.variant.use_map_timeframe:
            reaction_start = m1[cutoff].open_time
            m15 = await self._closed(account.id, symbol, Timeframe.M15, cfg.map_bars)
            # only bars that had closed before the reaction window: the map is what was known before the sweep
            map_candles = [c for c in m15 if c.open_time + timedelta(minutes=15) <= reaction_start]
        outcome = evaluate_setup(
            SetupProposalInput(
                symbol=symbol, h4_candles=h4, d1_candles=d1, h1_candles=h1, map_candles=map_candles,
                context_candles=m1[:cutoff],
                reaction_candles=m1[cutoff:], swing_lookback=cfg.swing_lookback,
                equal_level_tolerance=cfg.equal_level_tolerance, session_windows=list(DEFAULT_SESSION_WINDOWS),
                atr_period=cfg.atr_period, min_body_atr_multiple=cfg.min_body_atr_multiple,
                min_fvg_size=cfg.min_fvg_size, spread_buffer=cfg.spread_buffer, spread=tick.spread,
                commission=commission_in_price(limits.commission_per_lot_round_trip, spec) if spec else 0.0,
                cost_threshold=limits.cost_threshold, min_risk_reward=cfg.min_risk_reward,
                level_decimals=cfg.level_decimals,
            ),
            self.definition.variant,
        )  # fmt: skip
        self._last_candle[key] = candle_at
        return candle_at, outcome

    @staticmethod
    def _to_evaluation(strategy_id: str, symbol: str, candle_at: datetime, outcome: SetupOutcome) -> StrategyEvaluation:
        if isinstance(outcome, ProposedOutcome):
            p = outcome.proposal
            return StrategyEvaluation(
                strategy_id=strategy_id, symbol=symbol, event_at=p.detected_at, status="proposed", side=p.side,
                swept_level_kind=p.swept_level_kind.value, swept_level_price=p.swept_level_price,
                entry_price=p.entry_price, stop_loss=p.stop_loss, take_profit=p.take_profit, cost_ratio=p.cost_ratio,
                risk_reward_ratio=p.risk_reward_ratio,
            )  # fmt: skip
        return StrategyEvaluation(
            strategy_id=strategy_id,
            symbol=symbol,
            event_at=candle_at,
            status="blocked",
            stage=outcome.stage.value,
            detail=outcome.detail,
        )

    # ------------------------------------------------------------------------------------------ Strategy → Risk → Execution
    async def _hand_over(self, account: Account, proposal: SetupProposal) -> None:
        """A fresh proposal becomes an intent, the intent gets its risk decision, and only an approved decision reaches execution."""
        now = self._clock.now()
        if now - proposal.detected_at > self.config.act_within:
            return  # recorded as a measurement, but the market has moved: never acted on
        if await self._repos.strategy.get_intent(proposal.proposal_id) is not None:
            return  # this setup was handled already
        intent = TradeIntent(
            intent_id=proposal.proposal_id, account_id=account.id,
            strategy_id=self.definition.strategy_id, strategy_version=self.definition.version, symbol=proposal.symbol, side=proposal.side, order_type=OrderKind.LIMIT,
            entry_price=proposal.entry_price, stop_loss=proposal.stop_loss, take_profit=proposal.take_profit,
            created_at=now, expires_at=now + self.config.intent_ttl,
            rationale=(
                f"{self.definition.strategy_id}: {proposal.swept_level_kind.value} swept at {proposal.swept_level_price:g}, "
                f"displacement at {proposal.detected_at.isoformat()}"
            ),
            details={
                "costRatio": proposal.cost_ratio, "riskRewardRatio": proposal.risk_reward_ratio,
                "sweptLevelKind": proposal.swept_level_kind.value, "sweptLevelPrice": proposal.swept_level_price,
            },
        )  # fmt: skip
        await self._repos.strategy.record_intent(intent)  # persisted before anyone acts on it
        await self._events.publish(
            TradeIntentCreated(account_id=account.id, correlation_id=intent.intent_id, intent=intent)
        )

        decision = await self._risk.review(intent)
        if not decision.approved or decision.approved_volume is None:
            await self._events.publish(
                TradeRejected(
                    account_id=account.id, correlation_id=intent.intent_id, intent_id=intent.intent_id, stage="risk",
                    reasons=decision.reasons,
                )
            )  # fmt: skip
            return

        outcome = await self._execution.submit(
            ExecutionRequest(
                command_id=f"cmd-{intent.intent_id}"[:64], account_id=account.id, kind=CommandKind.OPEN,
                symbol=intent.symbol, side=intent.side, order_type=intent.order_type, volume=decision.approved_volume,
                price=intent.entry_price, stop_loss=intent.stop_loss, take_profit=intent.take_profit,
                strategy_id=self.definition.strategy_id, strategy_version=self.definition.version,
                risk_decision_id=decision.decision_id,
            ),
            automatic=True,
        )  # fmt: skip
        if outcome.rejections:
            await self._events.publish(
                TradeRejected(
                    account_id=account.id, correlation_id=intent.intent_id, intent_id=intent.intent_id,
                    stage="execution", reasons=[f"{r.code.value}: {r.detail}" for r in outcome.rejections],
                )
            )  # fmt: skip
