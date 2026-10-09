"""StrategyService: S01 on the live candles of the active account — what it records, when it stays silent, and how far a proposal is
allowed to travel (Strategy → Risk → Execution), with every mode of the autonomy ladder.

The market is the reference S01 scenario (``tests/unit/domain/s01/scenario.py``) stretched to EURUSD prices and shifted in time so its
last M1 candle closed a minute ago, inside the New York AM killzone — fed to the service through the candle reader, the way the real
worker would."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.support.core import Core, make_ready_core
from tests.support.harness import Harness
from tests.unit.domain.s01.scenario import BEARISH_HTF, BULLISH_HTF, CONTEXT, H1_DISCOUNT, REACTION
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.events import (
    CandleClosed,
    StrategyEvaluationCompleted,
    StrategyEvaluationStarted,
    TradeIntentCreated,
    TradeRejected,
)
from trading_os.domain.execution.commands import CommandState, ExecutionCommand
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Timeframe
from trading_os.domain.strategy.evaluation import StrategyEvaluation
from trading_os.domain.strategy.s01.config import S01Config
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.services.strategy import STRATEGY_ID, StrategyService
from trading_os.shared.errors import Unavailable

pytestmark = pytest.mark.db


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


SYMBOL = "EURUSDm"
CONFIG = S01Config(
    swing_lookback=1,
    equal_level_tolerance=0.003,
    min_fvg_size=0.002,
    spread_buffer=0.0005,
    reaction_window_m1_bars=8,  # three calm candles and the scenario's five reaction candles
    act_within=timedelta(minutes=3),
)  # the scenario's thresholds scaled with its prices (x0.01): 0.3 -> 0.003, 0.2 -> 0.002, 0.05 -> 0.0005. The levels keep two decimals
# (the original's rounding), which the scale makes exact: 99.0 -> 0.99, 105.0 -> 1.05
# the scenario's thresholds, stretched with its prices (x0.002): 0.3 -> 0.0006, 0.2 -> 0.0004, 0.05 -> 0.0001


def price(p: float) -> float:
    return round(p / 100, 5)


class Market:
    """What the candle reader answers: the scenario, per timeframe, shifted so its last M1 candle opened a minute before the clock.

    Three calm candles sit between the context and the reaction, so that the reaction window (eight bars) still holds the sweep and the
    displacement when one more candle has closed — the way the real window of thirty bars keeps seeing a setup on consecutive candles."""

    def __init__(self, core: Core, *, htf_d1: list[Candle] | None = None, h1: list[Candle] | None = None) -> None:
        calm = [
            CONTEXT[-1].model_copy(update={"open_time": CONTEXT[-1].open_time + timedelta(minutes=i + 1)})
            for i in range(3)
        ]
        reaction = [c.model_copy(update={"open_time": c.open_time + timedelta(minutes=3)}) for c in REACTION]
        raw = [*CONTEXT, *calm, *reaction]
        now = core.h.clock.now()
        shift = (now - timedelta(minutes=1)) - raw[-1].open_time
        self.m1 = [self._fx(c, Timeframe.M1, shift) for c in raw]
        self.h1 = [self._fx(c, Timeframe.H1, shift) for c in (h1 or H1_DISCOUNT)]
        self.h4 = [self._fx(c, Timeframe.H4, shift) for c in BULLISH_HTF]
        self.d1 = [self._fx(c, Timeframe.D1, shift) for c in (htf_d1 or BULLISH_HTF)]
        self.fail: Exception | None = None
        self.requests: list[tuple[Timeframe, int]] = []

    @staticmethod
    def _fx(c: Candle, timeframe: Timeframe, shift: timedelta) -> Candle:
        return c.model_copy(
            update={
                "symbol": SYMBOL, "timeframe": timeframe, "open_time": c.open_time + shift, "open": price(c.open),
                "high": price(c.high), "low": price(c.low), "close": price(c.close), "closed": True,
            }
        )  # fmt: skip

    def advance(self, minutes: int = 1) -> None:
        """One more closed M1 candle, flat, so a later evaluation sees a new last candle but the same displacement."""
        last = self.m1[-1]
        self.m1.append(last.model_copy(update={"open_time": last.open_time + timedelta(minutes=1)}))

    async def candles(self, account_id: str, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        self.requests.append((timeframe, count))
        if self.fail is not None:
            raise self.fail
        return {Timeframe.M1: self.m1, Timeframe.H1: self.h1, Timeframe.H4: self.h4, Timeframe.D1: self.d1}[timeframe][
            -count:
        ]


async def rig(
    h: Harness, top: AutonomyMode = AutonomyMode.PAPER, *, quote: bool = True, **market_kwargs: list[Candle]
) -> tuple[Core, Market, StrategyService]:
    core = await make_ready_core(h, top=top, calendar=True)
    market = Market(core, **market_kwargs)
    core.c.market.recent_candles = market.candles  # type: ignore[method-assign]
    core.c.strategy.config = CONFIG
    if quote:
        core.terminal.set_quote(SYMBOL, 0.99840, 0.99848)
        await core.c.market.poll_ticks(core.account.id)  # type: ignore[union-attr]
    return core, market, core.c.strategy


def closed_candle(core: Core, symbol: str = SYMBOL, timeframe: Timeframe = Timeframe.M1) -> CandleClosed:
    assert core.account is not None
    candle = Candle(
        symbol=symbol, timeframe=timeframe, open_time=core.h.clock.now(), open=1.0, high=1.1, low=0.9, close=1.0, volume=1.0,
        closed=True,
    )  # fmt: skip
    return CandleClosed(account_id=core.account.id, candle=candle)


async def evaluated(core: Core, strategy: StrategyService) -> StrategyEvaluation | None:
    assert core.account is not None
    return await strategy.evaluate(core.account.id, SYMBOL)


async def evaluation(core: Core, strategy: StrategyService) -> StrategyEvaluation:
    """An evaluation that is expected to have happened."""
    result = await evaluated(core, strategy)
    assert result is not None
    return result


async def commands(core: Core) -> list[ExecutionCommand]:
    assert core.account is not None
    return await core.c.execution.recent(core.account.id, 50)


# ------------------------------------------------------------------------------------------------------ when it stays silent


async def test_nothing_is_evaluated_while_the_system_is_off_or_halted(h: Harness) -> None:
    core, _, strategy = await rig(h, AutonomyMode.OBSERVE)
    await core.c.autonomy.disarm(AutonomyMode.OFF)
    assert await evaluated(core, strategy) is None
    await core.c.autonomy.halt("test", actor="user")
    assert await evaluated(core, strategy) is None
    assert core.recorder.of(StrategyEvaluationStarted) == []
    assert await core.c.repos.strategy.evaluations_since(core.h.clock.now() - timedelta(days=1)) == []


async def test_only_the_active_accounts_watched_symbols_on_the_minute_chart_are_due(h: Harness) -> None:
    core, _, strategy = await rig(h, AutonomyMode.OBSERVE)
    other = closed_candle(core).model_copy(update={"account_id": "someone-else"})
    for event in (
        closed_candle(core, "GBPUSDm"),  # S01 v1 watches EURUSD only
        closed_candle(core, SYMBOL, Timeframe.M5),  # one evaluation per closed M1 candle
        other,
    ):
        await core.c.events.publish(event)
    assert await strategy.run_pending() == 0
    await core.c.events.publish(closed_candle(core))
    assert await strategy.run_pending() == 1
    assert await strategy.run_pending() == 0  # it was drained


async def test_a_candle_already_evaluated_is_not_evaluated_twice(h: Harness) -> None:
    core, market, strategy = await rig(h, AutonomyMode.OBSERVE)
    assert await evaluated(core, strategy) is not None
    asked = len(market.requests)
    assert await evaluated(core, strategy) is None
    assert len(market.requests) == asked + 1  # only the M1 read that tells it nothing is new


async def test_without_a_live_quote_or_a_timeframe_the_cycle_is_skipped_and_nothing_is_recorded(h: Harness) -> None:
    core, market, strategy = await rig(h, AutonomyMode.OBSERVE, quote=False)
    core.c.market.forget(core.account.id)  # type: ignore[union-attr]
    assert await evaluated(core, strategy) is None  # no spread to read: never guessed
    core.terminal.set_quote(SYMBOL, 0.9984, 0.99848)
    await core.c.market.poll_ticks(core.account.id)  # type: ignore[union-attr]
    market.d1 = []
    assert await evaluated(core, strategy) is None  # a timeframe we do not have is not evaluated as if we did
    assert await core.c.repos.strategy.evaluations_since(core.h.clock.now() - timedelta(days=1)) == []


# ------------------------------------------------------------------------------------------------------ the measurement


async def test_each_stage_where_the_sequence_stops_is_recorded_once_per_candle(h: Harness) -> None:
    core, _, strategy = await rig(
        h, AutonomyMode.OBSERVE, htf_d1=list(BEARISH_HTF)
    )  # H4 bullish, D1 bearish: they disagree
    first = await evaluation(core, strategy)
    assert (first.status, first.stage) == ("blocked", "bias")
    rows = await core.c.repos.strategy.evaluations_since(core.h.clock.now() - timedelta(days=1))
    assert [(r.status, r.stage, r.symbol) for r in rows] == [("blocked", "bias", SYMBOL)]
    assert rows[0].event_at == first.event_at
    completed = core.recorder.of(StrategyEvaluationCompleted)
    assert [(e.outcome, e.stage, e.strategy_id) for e in completed] == [("blocked", "bias", STRATEGY_ID)]
    assert core.recorder.of(TradeIntentCreated) == []  # nothing proposed, nothing handed over


async def test_the_preconditions_come_first_and_the_calendar_fails_closed(h: Harness) -> None:
    core = await make_ready_core(h, top=AutonomyMode.OBSERVE, calendar=False)  # a calendar that never synced
    market = Market(core)
    core.c.market.recent_candles = market.candles  # type: ignore[method-assign]
    core.c.strategy.config = CONFIG
    core.terminal.set_quote(SYMBOL, 0.9984, 0.99848)
    await core.c.market.poll_ticks(core.account.id)  # type: ignore[union-attr]
    outcome = await evaluation(core, core.c.strategy)
    assert (outcome.status, outcome.stage) == ("blocked", "precondition_calendar")
    assert outcome.detail is not None and "failing closed" in outcome.detail
    assert market.requests == [
        (Timeframe.M1, CONFIG.m1_bars)
    ]  # nothing else was even read: « il n'y a pas de recherche »


async def test_an_active_lockout_stops_the_search_before_it_starts(h: Harness) -> None:
    core, _, strategy = await rig(h, AutonomyMode.OBSERVE)
    await core.c.risk.engage_kill_switch(core.account.id)  # type: ignore[union-attr]
    outcome = await evaluation(core, strategy)
    assert (outcome.status, outcome.stage) == ("blocked", "precondition_lockout")


async def test_the_trade_limit_of_the_day_is_a_precondition_too(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    core, _, strategy = await rig(h, AutonomyMode.OBSERVE)
    status = core.c.risk.status(core.account.id)  # type: ignore[union-attr]
    assert status is not None
    monkeypatch.setattr(
        core.c.risk, "status", lambda account_id: status.model_copy(update={"trades_today": status.max_trades_per_day})
    )
    outcome = await evaluation(core, strategy)
    assert (outcome.stage, outcome.detail) == (
        "precondition_trades_limit",
        f"{status.max_trades_per_day}/{status.max_trades_per_day} trades today",
    )


async def test_outside_the_killzone_nothing_is_searched(h: Harness) -> None:
    core, market, strategy = await rig(h, AutonomyMode.OBSERVE)
    shift = timedelta(hours=8)  # 03:59 UTC is 23:59 in New York the evening before
    market.m1 = [c.model_copy(update={"open_time": c.open_time - shift}) for c in market.m1]
    outcome = await evaluation(core, strategy)
    assert (outcome.stage, outcome.detail) == (
        "precondition_session_window",
        "outside the London/NY AM killzone (NY time)",
    )


# ------------------------------------------------------------------------------------------------------ a proposal


async def test_a_complete_setup_is_proposed_and_its_row_is_keyed_by_the_displacement(h: Harness) -> None:
    core, market, strategy = await rig(h, AutonomyMode.OBSERVE)
    first = await evaluation(core, strategy)
    assert first.status == "proposed" and first.side is not None and first.side.value == "buy"
    assert first.event_at == market.m1[-1].open_time  # the displacement was the last candle
    assert (first.swept_level_kind, first.take_profit) == ("equal_lows", price(105))

    market.advance()  # a new closed candle: the same displacement is re-detected
    again = await evaluated(core, strategy)
    assert again is not None and again.event_at == first.event_at
    rows = await core.c.repos.strategy.evaluations_since(core.h.clock.now() - timedelta(days=1))
    assert [r.status for r in rows] == ["proposed"]  # one real event, one row — not a stream of duplicates


async def test_in_observe_the_intent_and_the_refusal_are_recorded_and_nothing_is_sent(h: Harness) -> None:
    core, _, strategy = await rig(h, AutonomyMode.OBSERVE)
    evaluation = await evaluated(core, strategy)
    assert evaluation is not None
    (created,) = core.recorder.of(TradeIntentCreated)
    intent = await core.c.repos.strategy.get_intent(created.intent.intent_id)
    assert intent is not None and intent.strategy_id == STRATEGY_ID and intent.order_type.value == "limit"
    assert intent.entry_price == pytest.approx(price(99.85)) and intent.stop_loss == pytest.approx(price(98.65))
    decisions = await core.c.repos.risk.recent_decisions(core.account.id, 10)  # type: ignore[union-attr]
    assert [d.approved for d in decisions] == [False] and "autonomy_not_permitting" in decisions[0].reasons
    (rejected,) = core.recorder.of(TradeRejected)
    assert (rejected.stage, rejected.intent_id) == ("risk", intent.intent_id)
    assert await commands(core) == [] and core.link.lines == []  # OBSERVE sends nothing, and no command is even created


async def test_in_paper_an_approved_proposal_meets_the_engines_refusal_of_a_limit_order_it_cannot_carry(
    h: Harness,
) -> None:
    core, _, strategy = await rig(h, AutonomyMode.PAPER)
    await evaluated(core, strategy)
    decisions = await core.c.repos.risk.recent_decisions(core.account.id, 10)  # type: ignore[union-attr]
    assert [d.approved for d in decisions] == [True], decisions[0].reasons
    (command,) = await commands(core)
    assert command.state is CommandState.REJECTED and command.reject_code == "ORDER_TYPE_UNSUPPORTED"
    assert command.request.risk_decision_id == decisions[0].decision_id
    assert command.request.volume == decisions[0].approved_volume
    (rejected,) = core.recorder.of(TradeRejected)
    assert rejected.stage == "execution" and "ORDER_TYPE_UNSUPPORTED" in rejected.reasons[0]
    assert core.link.lines == []  # and nothing reached the agent


async def test_a_setup_is_handled_once_whatever_the_mode_does_afterwards(h: Harness) -> None:
    core, market, strategy = await rig(h, AutonomyMode.OBSERVE)
    await evaluated(core, strategy)  # refused in OBSERVE
    await core.c.autonomy.arm(AutonomyMode.PAPER)  # the human climbs while the same setup is still in the window
    market.advance()
    await evaluated(core, strategy)
    assert len(core.recorder.of(TradeIntentCreated)) == 1  # a stale setup is not resurrected by a higher mode
    assert await commands(core) == []
    assert len(await core.c.repos.risk.recent_decisions(core.account.id, 10)) == 1  # type: ignore[union-attr]


async def test_a_proposal_that_is_too_old_is_a_measurement_not_an_order(h: Harness) -> None:
    core, _, strategy = await rig(h, AutonomyMode.PAPER)
    core.h.clock.advance(minutes=10)  # the displacement is ten minutes old when the service finally looks at it
    evaluation = await evaluated(core, strategy)
    assert evaluation is not None and evaluation.status == "proposed"
    assert core.recorder.of(TradeIntentCreated) == [] and await commands(core) == []


# ------------------------------------------------------------------------------------------------------ when its inputs fail


async def test_a_failing_feed_is_kept_for_the_readiness_check_not_hidden(h: Harness) -> None:
    core, market, strategy = await rig(h, AutonomyMode.OBSERVE)
    account = await core.c.accounts.effective(core.account.id)  # type: ignore[union-attr]
    assert strategy.readiness(account).ok is False and "has not evaluated" in strategy.readiness(account).detail
    market.fail = WorkerError("boom", code="exception")
    assert await evaluated(core, strategy) is None
    fact = strategy.readiness(account)
    assert fact.ok is False and "the last evaluation failed" in fact.detail and "boom" not in fact.detail
    market.fail = Unavailable("database unavailable", code="database_unavailable")
    assert await evaluated(core, strategy) is None and strategy.readiness(account).ok is False
    market.fail = None
    assert await evaluated(core, strategy) is not None
    fact = strategy.readiness(account)
    assert fact.ok is True and "S01 evaluated EURUSDm" in fact.detail


async def test_the_strategy_is_not_valid_when_silent_on_an_open_market_or_when_the_account_is_not_the_active_one(
    h: Harness,
) -> None:
    core, _, strategy = await rig(h, AutonomyMode.OBSERVE)
    account = await core.c.accounts.effective(core.account.id)  # type: ignore[union-attr]
    await evaluated(core, strategy)
    assert strategy.readiness(account).ok is True
    core.h.clock.advance(minutes=11)  # (a Wednesday: the market is open)
    assert "silent" in strategy.readiness(account).detail and strategy.readiness(account).ok is False
    assert (
        strategy.readiness(account.model_copy(update={"id": "another"})).detail
        == "S01 runs for the active account only"
    )


async def test_an_error_in_a_pending_evaluation_is_counted_by_the_scheduler_not_swallowed(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    core, _, strategy = await rig(h, AutonomyMode.OBSERVE)

    async def broken(account_id: str, symbol: str) -> None:
        raise RuntimeError("bug")

    monkeypatch.setattr(strategy, "evaluate", broken)
    await core.c.events.publish(closed_candle(core))
    with pytest.raises(RuntimeError):
        await strategy.run_pending()
    assert strategy.last_error == "RuntimeError"
