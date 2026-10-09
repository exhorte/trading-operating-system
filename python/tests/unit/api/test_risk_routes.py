"""The risk routes: the state and the verdict (read), the review of a trade (the decision is recorded either way) and the lockout
ledger (the kill switch a person pulls, the acknowledgement a person gives)."""

from __future__ import annotations

import pytest

from tests.support.api import Api, create_second, open_api, quoted, review_body
from tests.support.harness import Harness
from trading_os.domain.autonomy.state import AutonomyMode

pytestmark = pytest.mark.db


# ------------------------------------------------------------------------------------------------------ reading


async def test_the_state_is_the_risk_read_model_with_its_limits(api: Api) -> None:
    response = await api.get("/api/risk/state")
    body = response.json()
    assert response.status_code == 200
    assert {"state", "dailyLossLimitPercent", "openRiskLimitPercent", "tradesToday", "gates", "evaluatedAt"} <= set(
        body
    )
    assert body["gates"] and all({"gateId", "label", "state", "detail"} <= set(g) for g in body["gates"])


async def test_an_account_that_is_not_connected_has_no_risk_state_and_an_unknown_one_is_not_found(api: Api) -> None:
    await create_second(api)
    absent = await api.get("/api/risk/state", accountId="exness-1000002")
    assert absent.status_code == 404 and absent.json()["code"] == "no_risk_state"
    unknown = await api.get("/api/risk/state", accountId="nope")
    assert unknown.status_code == 404 and unknown.json()["code"].endswith("not_found")


async def test_can_i_trade_answers_with_every_check_and_every_reason(api: Api) -> None:
    await quoted(api)
    body = (await api.get("/api/risk/can-i-trade", symbol="EURUSDm")).json()
    assert body["decision"] in {"ALLOWED", "DENIED"} and isinstance(body["reasons"], list)
    assert {"account_healthy", "news", "spread", "kill_switch"} <= {c["checkId"] for c in body["checks"]}
    assert (body["decision"] == "ALLOWED") == (body["reasons"] == [])  # a denial always says why
    assert (await api.get("/api/risk/can-i-trade", symbol="EUR USD")).status_code == 422


# ------------------------------------------------------------------------------------------------------ reviewing a trade


async def test_a_sound_trade_is_approved_with_a_size_and_the_decision_is_on_record(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.PAPER) as api:
        await quoted(api)
        response = await api.post("/api/risk/evaluate", review_body(api))
        decision = response.json()
        assert response.status_code == 201
        assert decision["approved"] is True, decision["reasons"]
        assert decision["approvedVolume"] > 0 and decision["sizing"]["volume"] == decision["approvedVolume"]
        assert (decision["symbol"], decision["side"], decision["stopLoss"]) == ("EURUSDm", "buy", 1.084)

        listed = (await api.get("/api/risk/decisions")).json()
        assert listed[0]["decisionId"] == decision["decisionId"]
        fetched = await api.get(f"/api/risk/decisions/{decision['decisionId']}")
        assert fetched.status_code == 200 and fetched.json() == decision


async def test_while_the_system_only_observes_every_review_is_refused_and_recorded(api: Api) -> None:
    await quoted(api)
    decision = (await api.post("/api/risk/evaluate", review_body(api))).json()
    assert decision["approved"] is False and "autonomy_not_permitting" in decision["reasons"]
    assert decision["approvedVolume"] is None  # nothing can be approved where nothing may be executed
    assert (await api.get(f"/api/risk/decisions/{decision['decisionId']}")).json()["approved"] is False


async def test_a_refusal_is_a_decision_too_with_its_reasons_and_no_size(api: Api) -> None:
    await quoted(api)
    wrong_side = review_body(api, stopLoss=1.0900)  # a stop above a buy
    response = await api.post("/api/risk/evaluate", wrong_side)
    decision = response.json()
    assert response.status_code == 201 and decision["approved"] is False
    assert (
        "stop_wrong_side" in decision["reasons"] and decision["sizing"] is None and decision["approvedVolume"] is None
    )
    assert (await api.get(f"/api/risk/decisions/{decision['decisionId']}")).json()["approved"] is False


async def test_a_review_carries_no_volume_and_no_unknown_field(api: Api) -> None:
    await quoted(api)
    for changes in ({"volume": 5.0}, {"lots": 1}, {"stopLoss": None}, {"entryPrice": 0}, {"side": "long"}):
        response = await api.post("/api/risk/evaluate", review_body(api, **changes))
        assert response.status_code == 422, changes  # the Risk Engine sizes the trade: a client cannot impose a size
    unknown = await api.post("/api/risk/evaluate", review_body(api, accountId="nope"))
    assert unknown.status_code == 404


async def test_an_unknown_decision_is_not_found(api: Api) -> None:
    response = await api.get("/api/risk/decisions/nope")
    assert response.status_code == 404 and response.json()["code"] == "decision_not_found"


# ------------------------------------------------------------------------------------------------------ the lockout ledger


async def test_the_kill_switch_locks_the_account_until_a_person_acknowledges_it(api: Api) -> None:
    account = api.core.account
    assert account is not None
    assert (await api.get("/api/risk/lockouts")).json() == {"active": None, "history": []}

    engaged = await api.post("/api/risk/lockouts", {"accountId": account.id})
    lockout = engaged.json()
    assert engaged.status_code == 201 and lockout["reason"] == "Kill switch manuel" and lockout["until"] is None
    again = await api.post("/api/risk/lockouts", {"accountId": account.id})
    assert again.status_code == 200 and again.json()["lockoutId"] == lockout["lockoutId"]  # engaged once

    await api.core.cycle()  # the next risk cycle sees it
    ledger = (await api.get("/api/risk/lockouts")).json()
    assert ledger["active"]["lockoutId"] == lockout["lockoutId"] and len(ledger["history"]) == 1
    state = (await api.get("/api/risk/state")).json()
    assert state["state"] == "locked" and state["lockoutReason"] == "Kill switch manuel"
    denied = (await api.get("/api/risk/can-i-trade")).json()
    assert denied["decision"] == "DENIED" and denied["reasons"]

    wrong = await api.post("/api/risk/lockouts/lockout-nope/acknowledge", {"accountId": account.id})
    assert wrong.status_code == 404 and wrong.json()["code"] == "lockout_not_active"
    cleared = await api.post(f"/api/risk/lockouts/{lockout['lockoutId']}/acknowledge", {"accountId": account.id})
    assert cleared.status_code == 200 and cleared.json() == {"lockoutId": lockout["lockoutId"]}

    ledger = (await api.get("/api/risk/lockouts")).json()
    assert ledger["active"] is None and ledger["history"][0]["clearedAt"] is not None
    gone = await api.post(f"/api/risk/lockouts/{lockout['lockoutId']}/acknowledge", {"accountId": account.id})
    assert gone.status_code == 404 and gone.json()["code"] == "lockout_not_active"


async def test_a_gesture_on_the_ledger_needs_an_account_that_exists(api: Api) -> None:
    assert (await api.post("/api/risk/lockouts", {"accountId": "nope"})).status_code == 404
    assert (await api.post("/api/risk/lockouts", {})).status_code == 422
    assert (await api.post("/api/risk/lockouts", {"accountId": "x", "reason": "because"})).status_code == 422
