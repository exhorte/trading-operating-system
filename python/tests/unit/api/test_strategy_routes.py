"""The strategy routes and the market context: what S01 saw and proposed, what it became, how it agrees with what was traded."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from tests.support.api import Api, create_second
from trading_os.domain.primitives import Side
from trading_os.domain.strategy.evaluation import StrategyEvaluation
from trading_os.domain.strategy.intent import OrderKind, TradeIntent
from trading_os.infrastructure.mt5.protocol import WorkerError

pytestmark = pytest.mark.db


async def record(api: Api, minutes_ago: int, status: str = "blocked", stage: str | None = "bias", **extra: Any) -> None:
    at = api.core.h.clock.now() - timedelta(minutes=minutes_ago)
    fields: dict[str, Any] = {"symbol": "EURUSDm", "event_at": at, "status": status, "stage": stage, "detail": "x"}
    if status == "proposed":
        fields |= {
            "stage": None, "detail": None, "side": Side.BUY, "swept_level_kind": "equal_lows", "swept_level_price": 1.083,
            "entry_price": 1.0845, "stop_loss": 1.0825, "take_profit": 1.095, "cost_ratio": 0.1, "risk_reward_ratio": 4.0,
        }  # fmt: skip
    await api.core.c.repos.strategy.record_evaluation(StrategyEvaluation.model_validate(fields | extra))


# ------------------------------------------------------------------------------------------------------ proposals


async def test_the_evaluations_come_back_newest_first_with_the_stage_where_the_others_stopped(api: Api) -> None:
    assert (await api.get("/api/strategy/proposals")).json() == []
    await record(api, 30, stage="bias")
    await record(api, 20, stage="liquidity")
    await record(api, 10, status="proposed")
    rows = (await api.get("/api/strategy/proposals")).json()
    assert [(r["status"], r["stage"]) for r in rows] == [
        ("proposed", None),
        ("blocked", "liquidity"),
        ("blocked", "bias"),
    ]
    assert rows[0]["side"] == "buy" and rows[0]["sweptLevelKind"] == "equal_lows" and rows[0]["riskRewardRatio"] == 4.0
    assert rows[0]["eventAt"].endswith("Z") and rows[0]["detail"] is None


async def test_the_evaluations_can_be_filtered_and_bounded(api: Api) -> None:
    for minutes in (50, 40, 30):
        await record(api, minutes, stage="sweep")
    await record(api, 5, status="proposed")
    proposed = (await api.get("/api/strategy/proposals", status="proposed")).json()
    assert [r["status"] for r in proposed] == ["proposed"]
    assert len((await api.get("/api/strategy/proposals", limit=2)).json()) == 2
    since = (api.core.h.clock.now() - timedelta(minutes=45)).isoformat()
    assert len((await api.get("/api/strategy/proposals", since=since)).json()) == 3  # the 50-minute-old one is out
    for bad in ({"status": "maybe"}, {"limit": 0}, {"limit": 5001}):
        assert (await api.get("/api/strategy/proposals", **bad)).status_code == 422


async def test_a_window_cannot_reach_back_more_than_a_month(api: Api) -> None:
    too_far = (api.core.h.clock.now() - timedelta(days=40)).isoformat()
    response = await api.get("/api/strategy/proposals", since=too_far)
    assert response.status_code == 422 and response.json()["code"] == "window_too_wide"


# ------------------------------------------------------------------------------------------------------ intents


async def test_the_intents_are_what_proposals_became_on_their_way_to_the_risk_engine(api: Api) -> None:
    account = api.core.account
    assert account is not None
    now = api.core.h.clock.now()
    intent = TradeIntent(
        intent_id="setup-EURUSDm-x", account_id=account.id, strategy_id="S01", strategy_version="1", symbol="EURUSDm",
        side=Side.BUY, order_type=OrderKind.LIMIT, entry_price=1.0845, stop_loss=1.0825, take_profit=1.095,
        created_at=now, expires_at=now + timedelta(minutes=2), rationale="S01: test", details={"costRatio": 0.1},
    )  # fmt: skip
    await api.core.c.repos.strategy.record_intent(intent)
    rows = (await api.get("/api/strategy/intents")).json()
    assert [(r["intentId"], r["strategyId"], r["orderType"], r["details"]) for r in rows] == [
        ("setup-EURUSDm-x", "S01", "limit", {"costRatio": 0.1})
    ]
    await create_second(api)
    assert (await api.get("/api/strategy/intents", accountId="exness-1000002")).json() == []  # another account's: none


# ------------------------------------------------------------------------------------------------------ agreement


async def test_agreement_classifies_proposals_and_trades_within_the_tolerance(api: Api) -> None:
    account = api.core.account
    assert account is not None
    await record(api, 3, status="proposed")  # a buy proposed three minutes ago, and taken
    await record(api, 60, status="proposed", side=Side.SELL)  # a sell proposed an hour ago, nobody took it
    api.core.terminal.add_position(identifier=501, symbol="EURUSDm", side=0, volume=0.05, price_open=1.0845, sl=1.0825)
    api.core.terminal.add_position(
        identifier=502, symbol="GBPUSDm", side=1, volume=0.05, price_open=1.27, sl=1.275, opened_server_time=None
    )
    await api.core.c.positions.poll(account.id)
    rows = (await api.get("/api/strategy/agreement")).json()
    by_class = {r["agreement"]: r for r in rows}
    assert by_class["PROPOSE_ET_PRIS"]["brokerPositionId"] == "501"
    assert by_class["PROPOSE_ET_REFUSE"]["side"] == "sell" and by_class["PROPOSE_ET_REFUSE"]["tradeOpenedAt"] is None
    assert by_class["PRIS_SANS_PROPOSITION"]["brokerPositionId"] == "502"  # the class that matters most
    assert len(rows) == 3


async def test_a_trade_outside_the_tolerance_of_the_proposal_is_not_the_same_trade(api: Api) -> None:
    account = api.core.account
    assert account is not None
    await record(api, 30, status="proposed")
    api.core.terminal.add_position(identifier=503, symbol="EURUSDm", side=0, volume=0.05, price_open=1.0845, sl=1.0825)
    await api.core.c.positions.poll(account.id)
    narrow = {r["agreement"] for r in (await api.get("/api/strategy/agreement", toleranceMinutes=5)).json()}
    assert narrow == {"PROPOSE_ET_REFUSE", "PRIS_SANS_PROPOSITION"}
    wide = {r["agreement"] for r in (await api.get("/api/strategy/agreement", toleranceMinutes=45)).json()}
    assert wide == {"PROPOSE_ET_PRIS"}
    for bad in (0, -1, 121, "soon"):
        assert (await api.get("/api/strategy/agreement", toleranceMinutes=bad)).status_code == 422


# ------------------------------------------------------------------------------------------------------ market context


async def test_the_market_context_is_the_engines_snapshot_at_the_last_closed_candle(api: Api) -> None:
    response = await api.get("/api/market/EURUSDm/context", timeframe="M5", count=200)
    body = response.json()
    assert response.status_code == 200
    assert (body["symbol"], body["timeframe"], body["maxScore"]) == ("EURUSDm", "M5", 10)
    assert body["bias"] in {"bullish", "bearish", "neutral"} and body["session"]
    assert [c["label"] for c in body["scoreBreakdown"]] == [
        "Structure",
        "Liquidity",
        "PD arrays",
        "Session",
        "Prem/Disc",
    ]
    assert sum(c["score"] for c in body["scoreBreakdown"]) == body["score"]
    assert {
        "lastStructureShift",
        "activeLiquidityLevels",
        "activeFairValueGaps",
        "activeOrderBlocks",
        "computedAt",
    } <= set(body)


async def test_the_context_needs_a_connected_account_a_known_timeframe_and_a_readable_terminal(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    await create_second(api)
    away = await api.get("/api/market/EURUSDm/context", accountId="exness-1000002")
    assert away.status_code == 409 and away.json()["code"] == "account_not_connected"
    for bad in ({"timeframe": "M7"}, {"count": 19}, {"count": 2001}):
        assert (await api.get("/api/market/EURUSDm/context", **bad)).status_code == 422

    async def broken(*args: object, **kwargs: object) -> None:
        raise WorkerError("secret internals", code="exception")

    monkeypatch.setattr(api.core.c.market, "recent_candles", broken)
    down = await api.get("/api/market/EURUSDm/context")
    assert down.status_code == 503 and down.json()["code"] == "mt5_unreadable" and "secret" not in down.text
