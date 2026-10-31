"""The market routes: quotes, specifications, candles, the news calendar — read-only, from the account's own terminal."""

from __future__ import annotations

import pytest

from tests.support.api import Api, create_second, open_api, quoted
from tests.support.harness import Harness
from trading_os.infrastructure.mt5.protocol import WorkerError

pytestmark = pytest.mark.db


async def test_the_calendar_is_known_once_synced(api: Api) -> None:
    body = (await api.get("/api/market/calendar")).json()
    assert body["releases"] and body["syncedAt"] is not None
    assert {"releaseId", "label", "scheduledAt"} <= set(body["releases"][0])


async def test_a_calendar_never_synced_is_unknown_never_silently_empty(h: Harness) -> None:
    async with open_api(h, calendar=False) as never_synced:  # no FRED key: the news gate fails closed on exactly this
        body = (await never_synced.get("/api/market/calendar")).json()
        assert body["releases"] is None  # unknown is not « nothing scheduled »


async def test_quotes_are_the_watchlist_as_last_seen(api: Api) -> None:
    await quoted(api)
    ticks = (await api.get("/api/market/quotes")).json()
    eurusd = next(t for t in ticks if t["symbol"] == "EURUSDm")
    assert (eurusd["bid"], eurusd["ask"]) == (1.08492, 1.085) and eurusd["time"].endswith("Z")
    assert all(t["bid"] < t["ask"] for t in ticks)


async def test_one_symbol_is_its_last_quote_and_the_brokers_specification(api: Api) -> None:
    await quoted(api)
    body = (await api.get("/api/market/EURUSDm")).json()
    assert body["symbol"] == "EURUSDm" and body["tick"]["ask"] == 1.085
    assert body["spec"]["digits"] == 5 and body["spec"]["contractSize"] == 100_000 and body["spec"]["volumeStep"] > 0


async def test_an_unknown_or_malformed_symbol_is_refused(api: Api) -> None:
    missing = await api.get("/api/market/NOSUCHSYMBOL")
    assert missing.status_code == 404 and missing.json()["code"] == "symbol_not_found"
    for path in ("/api/market/EUR%20USD", "/api/market/" + "X" * 33, "/api/market/EUR$USD/candles"):
        assert (await api.get(path)).status_code == 422, path


async def test_candles_come_oldest_first_and_only_the_newest_may_be_forming(api: Api) -> None:
    response = await api.get("/api/market/EURUSDm/candles", timeframe="M5", count=20)
    candles = response.json()
    assert response.status_code == 200 and len(candles) == 20
    assert [c["openTime"] for c in candles] == sorted(c["openTime"] for c in candles)
    assert candles[-1]["closed"] is False and all(c["closed"] for c in candles[:-1])
    assert all(c["low"] <= min(c["open"], c["close"]) <= max(c["open"], c["close"]) <= c["high"] for c in candles)
    assert {c["timeframe"] for c in candles} == {"M5"} and {c["symbol"] for c in candles} == {"EURUSDm"}


@pytest.mark.parametrize("params", [{"timeframe": "M7"}, {"count": 0}, {"count": 5001}, {"count": "many"}])
async def test_candle_parameters_are_bounded(api: Api, params: dict[str, object]) -> None:
    assert (await api.get("/api/market/EURUSDm/candles", **params)).status_code == 422


async def test_candles_of_an_account_that_is_not_connected_are_a_conflict_not_an_empty_list(api: Api) -> None:
    await create_second(api)
    response = await api.get("/api/market/EURUSDm/candles", accountId="exness-1000002")
    assert response.status_code == 409 and response.json()["code"] == "account_not_connected"


async def test_a_terminal_that_cannot_be_read_is_service_unavailable_without_its_internals(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args: object, **kwargs: object) -> None:
        raise WorkerError("secret internals: C:/MT5/terminal64.exe crashed", code="exception")

    monkeypatch.setattr(api.core.c.market, "recent_candles", broken)
    response = await api.get("/api/market/EURUSDm/candles")
    assert response.status_code == 503 and response.json()["code"] == "mt5_unreadable"
    assert response.json()["details"] == {"workerCode": "exception"} and "terminal64" not in response.text
