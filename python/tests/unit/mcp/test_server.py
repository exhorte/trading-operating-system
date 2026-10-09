"""The read-only MCP server: the six tools it offers, what they say, and the property that matters most — it can only read."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from tests.support.core import Core, make_ready_core
from tests.support.harness import Harness
from trading_os.domain.events import ExecutionUnknown
from trading_os.domain.market.models import Candle
from trading_os.domain.positions.models import ClosedTrade
from trading_os.domain.primitives import Side, Timeframe
from trading_os.domain.strategy.evaluation import StrategyEvaluation
from trading_os.infrastructure.database.pool import Database
from trading_os.mcp.server import build_server
from trading_os.mcp.tools import MAX_CANDLES, ReadOnlyTools

pytestmark = pytest.mark.db

TOOLS = {
    "get_trades", "get_lockouts", "get_candles", "get_setup_proposals", "get_execution_divergence", "get_compliance_violations",
}  # fmt: skip


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def rig(h: Harness, account_id: str | None = "unset") -> tuple[Core, ReadOnlyTools, MCPServer]:
    core = await make_ready_core(h)
    assert core.account is not None
    chosen = core.account.id if account_id == "unset" else account_id
    tools = ReadOnlyTools(repos=core.c.repos, journal=core.c.journal, clock=core.c.clock, account_id=lambda: chosen)
    return core, tools, build_server(tools)


async def call(server: MCPServer, name: str, **arguments: Any) -> Any:
    result = await server.call_tool(name, arguments)
    assert not getattr(result, "is_error", False), result
    text = result.content[0].text  # type: ignore[union-attr]
    return json.loads(text)


# ------------------------------------------------------------------------------------------------------ what it offers


async def test_exactly_six_tools_all_declared_read_only(h: Harness) -> None:
    _, _, server = await rig(h)
    listed = await server.list_tools()
    assert {t.name for t in listed} == TOOLS
    for tool in listed:
        hints = tool.annotations
        assert hints is not None, tool.name
        assert (hints.read_only_hint, hints.destructive_hint, hints.idempotent_hint, hints.open_world_hint) == (
            True, False, True, False
        ), tool.name  # fmt: skip
        assert tool.description, tool.name


async def test_the_tool_schemas_name_what_an_assistant_must_give(h: Harness) -> None:
    _, _, server = await rig(h)
    schemas = {t.name: t.input_schema for t in await server.list_tools()}
    assert (
        set(schemas["get_trades"]["required"]) == {"start", "end"} and "symbol" in schemas["get_trades"]["properties"]
    )
    assert set(schemas["get_candles"]["required"]) == {"symbol", "timeframe", "start", "end"}
    assert schemas["get_execution_divergence"]["properties"] == {}


# ------------------------------------------------------------------------------------------------------ what they say


async def record_trade(core: Core, position: str, symbol: str, pnl: float, ago_days: int = 1) -> None:
    assert core.account is not None
    await core.c.repos.positions.record_closed(
        ClosedTrade(
            account_id=core.account.id, broker_position_id=position, symbol=symbol, side=Side.BUY, volume=0.1,
            realized_pnl=pnl, exit_price=1.1, closed_at=core.h.clock.now() - timedelta(days=ago_days),
        )
    )  # fmt: skip


async def test_trades_come_back_as_the_journal_judged_them_and_can_be_filtered_by_symbol(h: Harness) -> None:
    core, _, server = await rig(h)
    await record_trade(core, "t1", "EURUSDm", -10.0)
    await record_trade(core, "t2", "XAUUSDm", 25.0, ago_days=2)
    window = {"start": "2026-10-01", "end": "2026-10-08"}  # (date-only, read as UTC; the rig's clock is 2026-10-07)
    everything = await call(server, "get_trades", **window)
    assert [t["brokerPositionId"] for t in everything] == ["t1", "t2"]
    assert {"realizedPnl", "rMultiple", "violations", "hasCapture"} <= set(everything[0])
    only_gold = await call(server, "get_trades", **window, symbol="XAUUSDm")
    assert [t["brokerPositionId"] for t in only_gold] == ["t2"]


async def test_lockouts_are_the_ledger_as_recorded(h: Harness) -> None:
    core, _, server = await rig(h)
    assert core.account is not None
    await core.c.risk.engage_kill_switch(core.account.id)
    windows = await call(server, "get_lockouts", until="2026-10-08T00:00:00Z")
    assert [w["reason"] for w in windows] == ["Kill switch manuel"] and windows[0]["clearedAt"] is None


async def test_candles_are_returned_as_stored_and_a_bad_timeframe_is_refused(h: Harness) -> None:
    core, _, server = await rig(h)
    bars = [
        Candle(symbol="EURUSDm", timeframe=Timeframe.M15, open_time=core.h.clock.now() - timedelta(minutes=15 * i),
               open=1.1, high=1.2, low=1.0, close=1.15, volume=10.0, closed=True)
        for i in range(1, 6)
    ]  # fmt: skip
    await core.c.repos.market.upsert_candles(bars)
    found = await call(server, "get_candles", symbol="EURUSDm", timeframe="M15", start="2026-10-07", end="2026-10-08")
    assert found["truncated"] is False and len(found["candles"]) == 5
    assert found["candles"][0]["openTime"] < found["candles"][-1]["openTime"]  # oldest first
    with pytest.raises(ToolError, match="unknown timeframe"):
        await server.call_tool(
            "get_candles", {"symbol": "EURUSDm", "timeframe": "M7", "start": "2026-10-07", "end": "2026-10-08"}
        )
    assert MAX_CANDLES == 20_000


async def test_the_strategy_evaluations_are_the_measurement_as_recorded(h: Harness) -> None:
    core, _, server = await rig(h)
    at = core.h.clock.now() - timedelta(minutes=5)
    await core.c.repos.strategy.record_evaluation(
        StrategyEvaluation(symbol="EURUSDm", event_at=at, status="blocked", stage="bias", detail="H4/D1 disagree")
    )
    rows = await call(server, "get_setup_proposals", since="2026-10-07T00:00:00Z")
    assert [(r["status"], r["stage"], r["detail"]) for r in rows] == [("blocked", "bias", "H4/D1 disagree")]


async def test_the_divergence_is_what_the_reconciliation_recorded(h: Harness) -> None:
    core, _, server = await rig(h)
    assert core.account is not None
    await core.c.events.publish(ExecutionUnknown(account_id=core.account.id, command_id="cmd-x", detail="no answer"))
    body = await call(server, "get_execution_divergence")
    assert body["inDoubt"] == []
    assert [(e["type"], e["payload"]["commandId"]) for e in body["events"]] == [("execution.unknown", "cmd-x")]


async def test_compliance_is_recomputed_from_the_facts(h: Harness) -> None:
    core, _, server = await rig(h)
    assert core.account is not None
    await record_trade(core, "t1", "EURUSDm", -10.0)
    await core.c.repos.positions.record_open(core.account.id, "t1", core.h.clock.now() - timedelta(days=1, hours=1))
    await core.c.risk.engage_kill_switch(core.account.id)  # (it opens after the trade: no violation)
    body = await call(server, "get_compliance_violations", start="2026-10-01", end="2026-10-08")
    assert 0.0 <= body["complianceRate"] <= 1.0
    assert [t["brokerPositionId"] for t in body["trades"]] == ["t1"] and isinstance(
        body["trades"][0]["violations"], list
    )


# ------------------------------------------------------------------------------------------------------ what it refuses


async def test_a_call_with_no_account_configured_says_what_to_set(h: Harness) -> None:
    _, _, server = await rig(h, account_id=None)
    with pytest.raises(ToolError, match="TRADING_OS_ACCOUNT_ID"):
        await server.call_tool("get_trades", {"start": "2026-10-01", "end": "2026-10-08"})


async def test_a_malformed_date_is_a_clear_refusal_not_a_crash(h: Harness) -> None:
    _, _, server = await rig(h)
    with pytest.raises(ToolError, match="not an ISO 8601"):
        await server.call_tool("get_trades", {"start": "last tuesday", "end": "2026-10-08"})
