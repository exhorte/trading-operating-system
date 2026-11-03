"""The two cockpit buttons over HTTP (ADR 0034): « Fermer toutes les positions » through the execution routes, « Démarrer le système »
through the system routes. The agent is a scripted double and the broker a simulated terminal: nothing can reach a real one."""

from __future__ import annotations

import pytest

from tests.support.api import Api
from tests.support.core import AGENT_MAGIC
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.services.startup import Timings

pytestmark = pytest.mark.db


async def close_capable(api: Api) -> None:
    login = api.core.login
    status = api.core.link.statuses[login]
    api.core.link.statuses[login] = status.model_copy(
        update={"capabilities": ["ping", "halt", "close", "cancel"], "mode": "confirm"}
    )


# ------------------------------------------------------------------------------------------------------ close all


async def test_the_preview_is_a_read_it_names_the_account_and_sends_nothing(api: Api) -> None:
    await close_capable(api)
    api.core.terminal.add_position(
        identifier=101, symbol="EURUSDm", side=0, volume=0.1, price_open=1.1, magic=AGENT_MAGIC
    )
    response = await api.get("/api/execution/close-all/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["account"]["loginMasked"] == "****0001" and body["account"]["environment"] == "DEMO"
    assert body["account"]["planMode"] == "OBSERVE"
    assert [p["positionId"] for p in body["positions"]] == ["101"] and body["canExecute"] is True
    assert len(body["batchId"]) == 12 and api.core.link.lines == []
    assert (await api.get("/api/execution/close-all/preview", accountId="nope")).status_code == 404


async def test_closing_needs_the_explicit_confirmation_in_the_body(api: Api) -> None:
    account = api.core.account
    assert account is not None
    base = {"accountId": account.id, "batchId": "batch000001", "positionIds": ["101"]}
    wrong = await api.post("/api/execution/close-all", {**base, "confirmation": "yes"})
    assert wrong.status_code == 422 and wrong.json()["code"] == "confirmation_required"
    missing = await api.post("/api/execution/close-all", base)
    assert missing.status_code == 422  # no confirmation at all
    unknown = await api.post("/api/execution/close-all", {**base, "confirmation": "CLOSE_ALL", "everything": True})
    assert unknown.status_code == 422  # a misspelt field is refused, not dropped
    assert api.core.link.lines == []


async def test_a_confirmed_close_returns_the_report_and_is_followed_by_its_id(api: Api) -> None:
    await close_capable(api)
    account = api.core.account
    assert account is not None
    api.core.terminal.add_position(
        identifier=101, symbol="EURUSDm", side=0, volume=0.1, price_open=1.1, magic=AGENT_MAGIC
    )
    await api.core.c.positions.poll(account.id)
    body = {"accountId": account.id, "batchId": "batch000002", "positionIds": ["101"], "confirmation": "CLOSE_ALL"}
    response = await api.post("/api/execution/close-all", body)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "IN_PROGRESS" and report["items"][0]["commandId"] == "ca-batch000002-101"
    assert report["counts"]["inProgress"] == 1 and len(api.core.link.lines) == 1

    again = await api.post("/api/execution/close-all", body)  # the double click
    assert again.status_code == 200 and len(api.core.link.lines) == 1

    followed = (await api.get("/api/execution/close-all/batch000002")).json()
    assert followed["batchId"] == "batch000002" and followed["items"][0]["status"] == "IN_PROGRESS"
    verified = await api.post("/api/execution/close-all/batch000002/verify")
    assert verified.status_code == 200 and verified.json()["final"] is False  # still waiting for the agent


async def test_an_unknown_batch_is_a_404(api: Api) -> None:
    response = await api.get("/api/execution/close-all/neverran0001")
    assert response.status_code == 404 and response.json()["code"] == "batch_not_found"
    assert (await api.post("/api/execution/close-all/neverran0001/verify")).status_code == 404


async def test_the_emergency_stop_does_not_close_anything(api: Api) -> None:
    """HALT and CLOSE ALL are two gestures (ADR 0034): stopping the entries never liquidates."""
    await close_capable(api)
    account = api.core.account
    assert account is not None
    api.core.terminal.add_position(
        identifier=101, symbol="EURUSDm", side=0, volume=0.1, price_open=1.1, magic=AGENT_MAGIC
    )
    await api.core.c.positions.poll(account.id)
    halted = await api.post("/api/autonomy/halt", {})
    assert halted.status_code == 200
    assert [line for _, line in api.core.link.lines if b"execution.close" in line] == []
    assert api.core.c.autonomy.halted()
    # and the way out is still open
    body = {"accountId": account.id, "batchId": "batch000003", "positionIds": ["101"], "confirmation": "CLOSE_ALL"}
    closing = await api.post("/api/execution/close-all", body)
    assert closing.status_code == 200 and closing.json()["counts"]["inProgress"] == 1


# ------------------------------------------------------------------------------------------------------ start


async def test_the_startup_status_lists_the_thirteen_stages(api: Api) -> None:
    body = (await api.get("/api/system/startup")).json()
    assert [s["order"] for s in body["stages"]] == list(range(1, 14))
    assert {s["state"] for s in body["stages"]} <= {
        "STOPPED",
        "STARTING",
        "READY",
        "RUNNING",
        "DEGRADED",
        "FAILED",
        "HALTED",
    }
    assert body["mode"] == "OBSERVE" and body["planMode"] == "OBSERVE" and body["entriesAuthorized"] is False
    assert body["realAccount"] is False and body["account"]["loginMasked"] == "****0001"
    assert len(body["checks"]) == 22 and "ladder" in body


async def test_starting_answers_202_and_never_climbs_past_confirm(api: Api) -> None:
    api.core.c.startup._timings = Timings(agent_wait_s=0, market_wait_s=0, step_s=0)
    await api.core.c.autonomy.disarm(AutonomyMode.OFF)
    response = await api.post("/api/system/startup", {})
    assert response.status_code == 202 and response.json()["state"] == "RUNNING"
    await api.core.c.startup.join()
    body = (await api.get("/api/system/startup")).json()
    assert body["run"]["state"] == "DONE" and body["mode"] == "OBSERVE"

    refused = await api.post("/api/system/startup", {"target": "ARMED"})
    assert refused.status_code == 422 and refused.json()["code"] == "invalid_target"
    unknown = await api.post("/api/system/startup", {"target": "OBSERVE", "autoArm": True})
    assert unknown.status_code == 422


async def test_authorising_automatic_trading_is_its_own_endpoint_and_one_rung(api: Api) -> None:
    early = await api.post("/api/system/startup/authorize-automatic", {})
    assert early.status_code == 422 and early.json()["code"] == "not_a_step_up"  # OBSERVE: nothing to authorise yet
    assert api.core.c.autonomy.mode is AutonomyMode.OBSERVE
