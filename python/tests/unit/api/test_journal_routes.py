"""The journal routes: closed trades with their verdicts, compliance, the file of one position, its captures."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.support.api import Api
from trading_os.domain.positions.models import ClosedTrade
from trading_os.domain.primitives import Side

pytestmark = pytest.mark.db


async def record_closed(api: Api, position_id: str = "T1", *, pnl: float = -12.5, ago_minutes: int = 5) -> None:
    account = api.core.account
    assert account is not None
    await api.core.h.repos.positions.record_closed(
        ClosedTrade(
            account_id=account.id, broker_position_id=position_id, symbol="EURUSDm", side=Side.BUY, volume=0.1,
            realized_pnl=pnl, exit_price=1.0845, closed_at=api.core.h.clock.now() - timedelta(minutes=ago_minutes),
        )
    )  # fmt: skip


async def test_an_empty_journal_is_empty_and_fully_compliant(api: Api) -> None:
    assert (await api.get("/api/journal/trades")).json() == []
    summary = (await api.get("/api/journal/compliance")).json()
    assert (summary["rate"], summary["tradeCount"], summary["breachedCount"], summary["byTrade"]) == (1.0, 0, 0, {})
    assert set(summary["byType"].values()) == {0} and set(summary["byType"]) == {
        "LOCKOUT_ACTIVE",
        "SESSION_WINDOW",
        "SIZE_POLICY",
    }


async def test_closed_trades_are_listed_newest_first_with_their_verdict(api: Api) -> None:
    await record_closed(api, "T-old", ago_minutes=60)
    await record_closed(api, "T-new", pnl=30.0, ago_minutes=5)
    trades = (await api.get("/api/journal/trades")).json()
    assert [t["brokerPositionId"] for t in trades] == ["T-new", "T-old"]
    first = trades[0]
    assert (first["symbol"], first["side"], first["realizedPnl"], first["hasCapture"]) == (
        "EURUSDm",
        "buy",
        30.0,
        False,
    )
    assert first["rMultiple"] is None and first["violations"] == []  # no entry or stop on record: nothing is guessed

    summary = (await api.get("/api/journal/compliance")).json()
    assert summary["tradeCount"] == 2 and 0.0 <= summary["rate"] <= 1.0


async def test_a_window_is_bounded_and_never_inverted(api: Api) -> None:
    now = api.core.h.clock.now()
    inverted = await api.get("/api/journal/trades", start=now.isoformat(), end=(now - timedelta(days=1)).isoformat())
    assert inverted.status_code == 422 and inverted.json()["code"] == "invalid_window"
    too_wide = await api.get(
        "/api/journal/compliance", start=(now - timedelta(days=400)).isoformat(), end=now.isoformat()
    )
    assert too_wide.status_code == 422 and too_wide.json()["code"] == "window_too_wide"
    old = await api.get(
        "/api/journal/trades", start=(now - timedelta(days=3)).isoformat(), end=(now - timedelta(days=2)).isoformat()
    )
    assert old.status_code == 200 and old.json() == []


async def test_the_file_of_a_closed_position_says_nobody_commanded_it(api: Api) -> None:
    await record_closed(api, "T1")
    response = await api.get("/api/journal/trades/T1")
    body = response.json()
    assert response.status_code == 200 and body["status"] == "closed" and body["manual"] is True
    assert body["trade"]["brokerPositionId"] == "T1" and body["command"] is None and body["decision"] is None
    assert body["intent"] is None  # a position opened by hand has no chain: it says so, it does not invent one


async def test_a_position_nobody_ever_heard_of_is_not_found(api: Api) -> None:
    for path in ("/api/journal/trades/nope", "/api/journal/captures/nope"):
        response = await api.get(path)
        assert response.status_code == 404, path
    assert (await api.get("/api/journal/trades/nope")).json()["code"] == "position_not_found"
    assert (await api.get("/api/journal/captures/nope")).json()["code"] == "capture_not_found"
    assert (await api.get("/api/journal/trades/bad id")).status_code == 422


async def test_an_open_position_has_its_entry_captured_at_the_moment_it_was_seen(api: Api) -> None:
    account = api.core.account
    assert account is not None
    api.core.terminal.add_position(
        identifier=777, symbol="EURUSDm", side=0, volume=0.05, price_open=1.085, sl=1.084, tp=1.088
    )
    await api.core.c.positions.poll(account.id)

    captures = await api.get("/api/journal/captures/777")
    entry = captures.json()["entry"]
    assert captures.status_code == 200 and captures.json()["exit"] is None
    assert (entry["kind"], entry["brokerPositionId"], entry["stopLoss"]) == ("entry", "777", 1.084)
    assert entry["windowStartUtc"] < entry["windowEndUtc"]  # the stored, never widened, window of candles

    body = (await api.get("/api/journal/trades/777")).json()
    assert body["status"] == "open" and body["manual"] is True and body["entryCapture"]["kind"] == "entry"
