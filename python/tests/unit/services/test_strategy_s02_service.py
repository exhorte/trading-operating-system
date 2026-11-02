"""S02 as a service (ADR 0024): measured on its own record, silent by default, and never in the way of S01."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.support.core import Core
from tests.support.harness import Harness
from tests.unit.domain.s01.scenario import H1_BULLISH_DISCOUNT
from tests.unit.services.test_strategy_service import CONFIG, commands, evaluated, rig
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.events import TradeIntentCreated
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.primitives import Timeframe
from trading_os.domain.strategy.s02 import S02Config, s02_variant
from trading_os.infrastructure.database.pool import Database
from trading_os.services.strategy import StrategyDefinition, StrategyService

pytestmark = pytest.mark.db


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


def s02_service(core: Core, *, acts: bool) -> StrategyService:
    config = S02Config(**CONFIG.model_dump())
    c = core.c
    return StrategyService(
        accounts=c.accounts, market=c.market, news=c.news, risk=c.risk, execution=c.execution, autonomy=c.autonomy,
        repos=c.repos, events=c.events, clock=c.clock, config=config,
        definition=StrategyDefinition(
            strategy_id="S02", version="1", variant=s02_variant(config), needs_d1=False, acts=acts
        ),
    )  # fmt: skip


async def rows(core: Core):  # type: ignore[no-untyped-def]
    return await core.c.repos.strategy.evaluations_since(core.h.clock.now() - timedelta(days=1))


async def test_each_strategy_is_recorded_on_its_own_record_for_the_same_candle(h: Harness) -> None:
    core, _, s01 = await rig(
        h, AutonomyMode.OBSERVE
    )  # the scenario's 1H has no structure: S02 stops at the bias, S01 proposes
    s02 = s02_service(core, acts=False)
    first = await evaluated(core, s01)
    second = await evaluated(core, s02)
    assert first is not None and first.strategy_id == "S01" and first.status == "proposed"
    assert second is not None and second.strategy_id == "S02" and (second.status, second.stage) == ("blocked", "bias")
    stored = await rows(core)
    assert sorted((r.strategy_id, r.status) for r in stored) == [("S01", "proposed"), ("S02", "blocked")]


async def test_a_measuring_s02_hands_nothing_to_the_risk_engine(h: Harness) -> None:
    core, _, _ = await rig(h, AutonomyMode.PAPER, h1=H1_BULLISH_DISCOUNT)
    s02 = s02_service(core, acts=False)
    result = await evaluated(core, s02)
    assert result is not None and result.status == "proposed" and result.strategy_id == "S02"
    assert core.recorder.of(TradeIntentCreated) == [] and await commands(core) == []
    assert await core.c.repos.risk.recent_decisions(core.account.id, 10) == []  # type: ignore[union-attr]
    assert [r.strategy_id for r in await rows(core)] == ["S02"]


async def test_a_trading_s02_goes_through_the_same_path_with_its_own_identity(h: Harness) -> None:
    core, _, s01 = await rig(h, AutonomyMode.PAPER, h1=H1_BULLISH_DISCOUNT)
    s02 = s02_service(core, acts=True)
    await evaluated(core, s01)
    await evaluated(core, s02)
    intents = {e.intent.strategy_id: e.intent for e in core.recorder.of(TradeIntentCreated)}
    assert set(intents) == {"S01", "S02"}
    assert intents["S02"].intent_id.startswith("setup-s02-") and intents["S01"].intent_id.startswith("setup-EURUSDm-")
    assert intents["S02"].order_type.value == "limit" and intents["S02"].rationale.startswith("S02:")
    placed = {c.request.strategy_id: c for c in await commands(core)}
    assert set(placed) == {"S01", "S02"}
    assert placed["S02"].state is CommandState.SIMULATED and placed["S02"].request.order_type.value == "limit"
    assert placed["S01"].command_id != placed["S02"].command_id


async def test_the_default_service_is_s01_and_s02_is_absent_unless_asked_for(h: Harness) -> None:
    core, _, s01 = await rig(h, AutonomyMode.OBSERVE)
    assert s01.definition.strategy_id == "S01" and s01.definition.needs_d1 and s01.definition.acts
    assert core.c.strategy_s02 is None  # STRATEGY_S02 defaults to « off »


async def test_s02_follows_the_setting(h: Harness) -> None:
    from tests.support.core import make_core

    measure = await make_core(h, settings={"strategy_s02": "measure"})
    assert measure.c.strategy_s02 is not None and not measure.c.strategy_s02.definition.acts


async def test_s02_reads_the_fifteen_minute_map_and_rests_its_limit_at_the_edge(h: Harness) -> None:
    core, market, _ = await rig(h, AutonomyMode.PAPER, h1=H1_BULLISH_DISCOUNT)
    s02 = s02_service(core, acts=False)
    result = await evaluated(core, s02)
    assert result is not None and result.status == "proposed"
    assert (Timeframe.M15, S02Config().map_bars) in market.requests  # the map was asked for, and for S02 only
    assert result.entry_price == pytest.approx(1.00008)  # the top of the FVG (1.0000) plus the live spread (0.00008)


async def test_without_the_fifteen_minute_series_s02_stops_at_the_range_and_says_why(h: Harness) -> None:
    core, market, _ = await rig(h, AutonomyMode.OBSERVE, h1=H1_BULLISH_DISCOUNT)
    market.m15 = []
    result = await evaluated(core, s02_service(core, acts=False))
    assert result is not None and (result.status, result.stage) == ("blocked", "dealing_range")
    assert result.detail is not None and "15m" in result.detail
