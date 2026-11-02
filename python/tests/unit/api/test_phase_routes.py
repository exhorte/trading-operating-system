"""The read routes added by the mission phases: the Guardian (ADR 0025), the promotion report (ADR 0027), why no trade (ADR 0028)."""

from __future__ import annotations

import pytest

from tests.support.api import Api

pytestmark = pytest.mark.db


async def test_the_guardian_report_is_there_before_its_first_cycle(api: Api) -> None:
    body = (await api.get("/api/guardian")).json()
    assert body["ran"] is False and body["actions"] == [] and body["verdict"]["flattenAll"] is False


async def test_the_guardian_report_follows_the_cycle(api: Api) -> None:
    await api.core.c.positions.poll(api.core.account.id)  # type: ignore[union-attr]
    await api.core.c.guardian.run()
    body = (await api.get("/api/guardian")).json()
    assert body["ran"] is True and body["accountId"] == api.core.account.id  # type: ignore[union-attr]
    assert body["recovery"].startswith("core started")


async def test_the_promotion_report_is_advisory_and_lists_each_climb(api: Api) -> None:
    body = (await api.get("/api/autonomy/promotion")).json()
    assert body["advisory"] is True
    assert [s["toMode"] for s in body["steps"]] == ["PAPER", "CONFIRM", "ARMED", "AUTONOMOUS"]
    assert all(c["status"] in {"met", "not_met", "not_measured"} for s in body["steps"] for c in s["criteria"])
    assert body["steps"][-1]["met"] is False  # nothing measured for the last climb: not met


async def test_why_no_trade_names_the_mode_first(api: Api) -> None:
    body = (await api.get("/api/why-no-trade")).json()
    assert body["headline"] and body["reasons"] and body["reasons"][0]["source"] == "mode"
    assert body["realOrdersPossible"] is False  # the test core is in OBSERVE
    assert {"mode", "ceiling", "reasons", "opportunities", "evaluations", "evaluatedAt"} <= set(body)
