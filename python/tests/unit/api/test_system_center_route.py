"""``GET /api/system/center`` and ``GET /api/system/mt5/terminals`` (ADR 0039 § 8, I8): reads of the MetaTrader terminals the launcher registered, with their agents and the reading of
their technical readiness. Reads that send nothing, change no mode and hold no secret."""

from __future__ import annotations

import json

import pytest

from tests.support.api import Api

pytestmark = pytest.mark.db


async def test_the_center_is_a_read_that_says_the_mode_and_sends_nothing_to_the_agent(api: Api) -> None:
    response = await api.get("/api/system/center")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "observedAt",
        "coreStatus",
        "executionMode",
        "agentsConnected",
        "mt5WorkersAlive",
        "terminals",
        "unregisteredAgents",
        "registryProblem",
        "recentEvents",
    }
    assert body["executionMode"] in {"OFF", "OBSERVE", "CONFIRM", "ARMED", "AUTONOMOUS", "HALTED"}
    assert api.core.link.lines == []


async def test_the_terminals_are_a_list_of_readings_each_with_its_own_verdict(api: Api) -> None:
    response = await api.get("/api/system/mt5/terminals")
    assert response.status_code == 200
    terminals = response.json()
    assert isinstance(terminals, list)
    for item in terminals:
        assert item["readiness"]["verdict"] in {"READY", "VALIDATING", "BLOCKED"}
        assert set(item["readiness"]["executionAuthorization"]) == {"allowed", "reasons"}


async def test_nothing_secret_is_in_what_the_center_says(api: Api) -> None:
    body = json.dumps((await api.get("/api/system/center")).json()).lower()
    for word in ("password", "secret", "apikey", "credential"):
        assert word not in body
    assert "token" not in body.replace("tokens", "")
