"""The execution routes: a command is a row first, its fate is the engine's (a refusal is an *outcome*, recorded with its reasons),
and what leaves the core depends on the mode the account is really in. Nothing here reaches a real terminal or a real agent: the
agent is a scripted link that records what it was told."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.api import Api, create_second, open_api, quoted, review_body
from tests.support.harness import Harness
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.commands import ExecutionRequest

pytestmark = pytest.mark.db


async def approved(api: Api, **changes: Any) -> dict[str, Any]:
    """A risk decision that approved a small buy, as the cockpit would have fetched it before ordering."""
    await quoted(api)
    decision: dict[str, Any] = (await api.post("/api/risk/evaluate", review_body(api, **changes))).json()
    assert decision["approved"], decision["reasons"]
    return decision


def open_command(decision: dict[str, Any], command_id: str = "cmd-api-1", **changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "commandId": command_id, "accountId": decision["accountId"], "kind": "OPEN", "symbol": decision["symbol"],
        "side": decision["side"], "volume": decision["approvedVolume"], "stopLoss": decision["stopLoss"],
        "takeProfit": decision["takeProfit"], "riskDecisionId": decision["decisionId"],
    }  # fmt: skip
    body.update(changes)
    return body


def codes(outcome: dict[str, Any]) -> set[str]:
    return {rejection["code"] for rejection in outcome["rejections"]}


# ------------------------------------------------------------------------------------------------------ the state


async def test_the_state_says_what_the_account_is_really_in_and_what_the_agent_is(api: Api) -> None:
    account = api.core.account
    assert account is not None
    body = (await api.get("/api/execution/state")).json()
    assert body["accountId"] == account.id and body["mode"] == "OBSERVE" and body["route"] == "none"
    assert body["agent"]["agentId"] == "mt5-execution-agent-7001" and body["agentLastHeartbeatAt"] is not None
    assert body["inDoubt"] == [] and body["recent"] == []
    assert body["reconciliation"]["readable"] is True  # the cycles behind the rig ran one
    assert (await api.get("/api/execution/state", accountId="nope")).status_code == 404


# ------------------------------------------------------------------------------------------------------ refusals are outcomes


async def test_a_command_without_an_approved_decision_is_refused_as_an_outcome_and_recorded(api: Api) -> None:
    account = api.core.account
    assert account is not None
    bare = {
        "commandId": "cmd-bare", "accountId": account.id, "kind": "OPEN", "symbol": "EURUSDm", "side": "buy", "volume": 0.5,
    }  # fmt: skip
    response = await api.post("/api/execution/commands", bare)
    outcome = response.json()
    assert response.status_code == 201  # recorded — the refusal is the outcome, not an HTTP error
    assert outcome["command"]["state"] == "REJECTED" and outcome["replayed"] is False
    assert {"RISK_NOT_APPROVED", "STOP_REQUIRED"} <= codes(outcome)  # every reason, not just the first
    assert outcome["command"]["rejectCode"] in codes(outcome)

    on_record = await api.get("/api/execution/commands/cmd-bare")
    assert on_record.status_code == 200 and on_record.json()["state"] == "REJECTED"
    assert [c["request"]["commandId"] for c in (await api.get("/api/execution/commands")).json()] == ["cmd-bare"]
    assert api.core.link.lines == []  # and nothing went anywhere


async def test_a_command_body_is_strict(api: Api) -> None:
    account = api.core.account
    assert account is not None
    base = {"commandId": "cmd-strict", "accountId": account.id, "symbol": "EURUSDm", "side": "buy", "volume": 0.1}
    for changes in (
        {"stopLos": 1.08},
        {"volume": 0},
        {"commandId": "x"},
        {"kind": "SELL_EVERYTHING"},
        {"side": "long"},
    ):
        response = await api.post("/api/execution/commands", {**base, **changes})
        assert response.status_code == 422, changes
    assert (await api.post("/api/execution/commands", {"accountId": account.id})).status_code == 422
    assert (await api.get("/api/execution/commands")).json() == []  # a malformed body leaves no trace


async def test_a_command_for_an_account_that_is_not_connected_is_refused_and_recorded(api: Api) -> None:
    await create_second(api)
    body = {"commandId": "cmd-away", "accountId": "exness-1000002", "symbol": "EURUSDm", "side": "buy", "volume": 0.1}
    outcome = (await api.post("/api/execution/commands", body)).json()
    assert outcome["command"]["state"] == "REJECTED" and "ACCOUNT_NOT_CONNECTED" in codes(outcome)


async def test_an_unknown_command_is_not_found_whatever_is_done_to_it(api: Api) -> None:
    assert (await api.get("/api/execution/commands/nope")).json()["code"] == "command_not_found"
    assert (await api.post("/api/execution/commands/nope/confirm")).status_code == 404
    assert (await api.post("/api/execution/commands/nope/cancel")).status_code == 404


# ------------------------------------------------------------------------------------------------------ the routes


async def test_paper_fills_in_process_at_the_live_quote_and_a_replay_is_the_same_command(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.PAPER) as api:
        decision = await approved(api)
        body = open_command(decision)
        first = await api.post("/api/execution/commands", body)
        outcome = first.json()
        assert first.status_code == 201 and outcome["replayed"] is False and outcome["rejections"] == []
        command = outcome["command"]
        assert command["state"] == "SIMULATED" and command["route"] == "paper" and command["mode"] == "PAPER"
        assert command["averagePrice"] == 1.085 and command["filledVolume"] == decision["approvedVolume"]
        assert api.core.link.lines == []  # PAPER never reaches an agent, let alone a broker

        again = await api.post("/api/execution/commands", body)  # the same commandId and content: the original
        assert again.status_code == 200 and again.json()["replayed"] is True
        assert again.json()["command"]["createdAt"] == command["createdAt"]

        other = await api.post("/api/execution/commands", {**body, "volume": decision["approvedVolume"] / 2})
        assert other.status_code == 409 and other.json()["code"] == "DUPLICATE_CONFLICT"  # same id, another order

        assert len((await api.get("/api/execution/commands")).json()) == 1  # one id, at most one execution


async def test_a_command_cannot_exceed_what_the_risk_engine_approved(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.PAPER) as api:
        decision = await approved(api)
        too_big = open_command(decision, "cmd-big", volume=decision["approvedVolume"] * 2)
        wrong_way = open_command(decision, "cmd-way", side="sell")
        looser = open_command(decision, "cmd-loose", stopLoss=decision["stopLoss"] - 0.0020)
        for body in (too_big, wrong_way, looser):
            outcome = (await api.post("/api/execution/commands", body)).json()
            assert outcome["command"]["state"] == "REJECTED", body["commandId"]
            assert "RISK_DECISION_MISMATCH" in codes(outcome), body["commandId"]


async def test_a_halted_system_refuses_every_command(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.PAPER) as api:
        decision = await approved(api)
        await api.post("/api/autonomy/halt", {})
        outcome = (await api.post("/api/execution/commands", open_command(decision))).json()
        assert outcome["command"]["state"] == "REJECTED" and "HALTED" in codes(outcome)


async def test_in_confirm_a_human_gesture_is_the_confirmation_and_the_command_goes_to_the_agent(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.CONFIRM) as api:
        decision = await approved(api)
        response = await api.post("/api/execution/commands", open_command(decision))
        command = response.json()["command"]
        assert response.status_code == 201 and command["state"] == "SENT" and command["route"] == "confirm"
        assert [login for login, _ in api.core.link.lines] == [api.core.login]
        assert b"cmd-api-1" in api.core.link.lines[0][1]  # the idempotency key travels with the order

        in_doubt = (await api.get("/api/execution/commands", inDoubt="true")).json()
        assert [c["request"]["commandId"] for c in in_doubt] == ["cmd-api-1"]
        state = (await api.get("/api/execution/state")).json()
        assert state["route"] == "confirm" and [c["request"]["commandId"] for c in state["inDoubt"]] == ["cmd-api-1"]

        late = await api.post("/api/execution/commands/cmd-api-1/cancel")  # already sent: it can no longer be withdrawn
        assert late.status_code == 409 and late.json()["code"] == "not_cancellable"


async def test_an_unreachable_agent_means_nothing_was_sent_and_the_command_says_so(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.CONFIRM) as api:
        decision = await approved(api)
        api.core.link.deliver = False  # the socket write fails
        outcome = (await api.post("/api/execution/commands", open_command(decision))).json()
        assert outcome["command"]["state"] == "FAILED" and outcome["command"]["rejectCode"] == "AGENT_UNREACHABLE"
        assert api.core.link.lines == []  # failed before sending, not in doubt: it is safe to ask again with a new id


async def test_a_pending_command_is_confirmed_or_withdrawn_by_a_person(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.CONFIRM) as api:
        waiting = []
        for index in (1, 2):
            decision = await approved(api)
            request = ExecutionRequest.model_validate(open_command(decision, f"cmd-auto-{index}"))
            outcome = await api.core.c.execution.submit(request, automatic=True)  # the strategy pipeline's way in
            assert outcome.awaiting_confirmation
            waiting.append(request.command_id)
        assert api.core.link.lines == []  # nothing is sent until a person says so

        withdrawn = await api.post(f"/api/execution/commands/{waiting[0]}/cancel")
        assert withdrawn.status_code == 200 and withdrawn.json()["state"] == "CANCELLED"

        confirmed = await api.post(f"/api/execution/commands/{waiting[1]}/confirm")
        assert confirmed.status_code == 200 and confirmed.json()["command"]["state"] == "SENT"
        assert len(api.core.link.lines) == 1 and waiting[1].encode() in api.core.link.lines[0][1]

        twice = await api.post(f"/api/execution/commands/{waiting[1]}/confirm")  # confirming again changes nothing
        assert twice.json()["replayed"] is True and len(api.core.link.lines) == 1
        gone = await api.post(f"/api/execution/commands/{waiting[0]}/cancel")
        assert gone.status_code == 409 and gone.json()["code"] == "not_cancellable"


# ------------------------------------------------------------------------------------------------------ reconciliation


async def test_the_last_reconciliation_is_readable_and_can_be_run_again(api: Api) -> None:
    first = (await api.get("/api/execution/reconciliation")).json()
    assert first["readable"] is True and first["mismatches"] == [] and first["positionsChecked"] == 0
    api.core.h.clock.advance(seconds=5)
    again = await api.post("/api/execution/reconciliation/run")
    assert again.status_code == 200 and again.json()["finishedAt"] > first["finishedAt"]
    assert (await api.get("/api/execution/reconciliation")).json()["finishedAt"] == again.json()["finishedAt"]


async def test_a_position_nobody_asked_for_is_a_critical_finding(api: Api) -> None:
    api.core.terminal.add_position(
        identifier=991, symbol="EURUSDm", side=0, volume=0.05, price_open=1.085, sl=1.084, magic=7001
    )
    await api.core.c.positions.poll(api.core.account.id)  # type: ignore[union-attr]
    report = (await api.post("/api/execution/reconciliation/run")).json()
    assert report["readable"] is True and report["positionsChecked"] == 1
    assert any(m["severity"] == "critical" for m in report["mismatches"]), report["mismatches"]


async def test_reconciling_an_account_that_is_not_connected_is_refused(api: Api) -> None:
    await create_second(api)
    refused = await api.post("/api/execution/reconciliation/run", accountId="exness-1000002")
    assert refused.status_code == 409 and refused.json()["code"] == "account_not_connected"
    nothing = await api.get("/api/execution/reconciliation", accountId="exness-1000002")
    assert nothing.status_code == 404 and nothing.json()["code"] == "no_reconciliation"
