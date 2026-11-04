"""``GET /api/system/live-metrics`` (ADR 0035, L1): a read that measures and sends nothing."""

from __future__ import annotations

import pytest

from tests.support.api import Api

pytestmark = pytest.mark.db


async def test_the_window_is_read_and_nothing_is_sent_to_the_agent(api: Api) -> None:
    await api.core.cycle()
    await api.core.c.tick_writer.flush()
    response = await api.get("/api/system/live-metrics", minutes=30)
    assert response.status_code == 200
    body = response.json()
    account = api.core.account
    assert account is not None
    assert body["windowMinutes"] == 30 and body["accountId"] == account.id
    assert {q["symbol"] for q in body["quotes"]} == {"EURUSDm", "XAUUSDm"}
    assert set(body["quotes"][0]) >= {"ticks", "spread", "receiptLagS", "lastTickAgeS", "marketOpen"}
    assert set(body["commands"]) >= {"ackS", "fillS", "totalS", "brokerRetcodes", "simulated", "inconsistent"}
    assert body["caveats"] and body["notMeasured"]
    assert api.core.link.lines == []  # a measure is not a command


async def test_the_default_window_is_an_hour_and_a_silly_one_is_refused(api: Api) -> None:
    assert (await api.get("/api/system/live-metrics")).json()["windowMinutes"] == 60
    for minutes in (0, 1441, -5):
        assert (await api.get("/api/system/live-metrics", minutes=minutes)).status_code == 422
    assert (await api.get("/api/system/live-metrics", accountId="nope")).status_code == 404
