"""The autonomy routes: the ladder climbed one rung at a time by a person, the lease he renews, the brake he pulls."""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.api import Api, open_api
from tests.support.harness import Harness
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.shared.errors import Unavailable

pytestmark = pytest.mark.db


async def mode_of(api: Api) -> str:
    return str((await api.get("/api/autonomy/state")).json()["state"]["mode"])


# ------------------------------------------------------------------------------------------------------ reading


async def test_the_state_is_the_ladder_the_ceiling_and_what_the_account_is_really_in(api: Api) -> None:
    body = (await api.get("/api/autonomy/state")).json()
    assert body["state"]["mode"] == "OBSERVE" and body["ceiling"] == "AUTONOMOUS" and body["effectiveMode"] == "OBSERVE"
    assert body["activeAccountId"] == api.core.account.id  # type: ignore[union-attr]
    assert "readiness" in body and body["state"]["leaseUntil"] is None


# ------------------------------------------------------------------------------------------------------ the ladder


async def test_the_ladder_is_climbed_one_rung_at_a_time(api: Api) -> None:
    up = await api.post("/api/autonomy/arm", {"target": "PAPER"})
    assert up.status_code == 200 and up.json()["mode"] == "PAPER"
    assert up.json()["lastTransition"]["fromMode"] == "OBSERVE"

    skipped = await api.post("/api/autonomy/arm", {"target": "ARMED"})
    assert skipped.status_code == 409 and skipped.json()["code"] == "skipped_rung"
    backwards = await api.post("/api/autonomy/arm", {"target": "OBSERVE"})  # arming never steps down: disarm does
    assert backwards.status_code == 409 and backwards.json()["code"] == "not_a_step_up"
    halting = await api.post("/api/autonomy/arm", {"target": "HALTED"})  # the halt is a brake, not a rung
    assert halting.status_code == 409 and halting.json()["code"] == "invalid_target"
    assert await mode_of(api) == "PAPER"


@pytest.mark.parametrize(
    "body",
    [{"target": "TURBO"}, {"target": "PAPER", "force": True}, {}, {"target": None}],
    ids=["unknown-mode", "unknown-field", "empty", "null"],
)
async def test_a_malformed_gesture_changes_nothing(api: Api, body: dict[str, Any]) -> None:
    response = await api.post("/api/autonomy/arm", body)
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"
    assert await mode_of(api) == "OBSERVE"


async def test_the_automatic_rungs_need_a_green_readiness_evaluated_for_the_call(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.CONFIRM) as api:
        api.core.link.statuses.clear()  # the execution agent is gone: no kill switch to rely on
        refused = await api.post("/api/autonomy/arm", {"target": "ARMED"})
        body = refused.json()
        assert refused.status_code == 403 and body["code"] == "not_ready"
        assert set(body["details"]["blockers"]) == {"kill_switch_available", "heartbeat"}
        assert await mode_of(api) == "CONFIRM"  # nothing moved

        await api.core.register_agent()  # it is back
        api.core.h.clock.advance(seconds=3)  # (the earlier red verdict is older than its short cache)
        armed = await api.post("/api/autonomy/arm", {"target": "ARMED"})
        assert armed.status_code == 200, armed.text
        lease = armed.json()["leaseUntil"]
        assert armed.json()["mode"] == "ARMED" and lease is not None


async def test_the_armed_window_is_renewed_by_the_human_and_stepping_down_is_always_allowed(h: Harness) -> None:
    async with open_api(h, top=AutonomyMode.ARMED) as api:
        before = (await api.get("/api/autonomy/state")).json()["state"]["leaseUntil"]
        assert before is not None
        api.core.h.clock.advance(minutes=10)
        stale = await api.post("/api/autonomy/renew")  # nothing was refreshed for ten minutes: not worth renewing
        assert stale.status_code == 403 and stale.json()["code"] == "not_ready"
        await api.core.cycle()
        renewed = await api.post("/api/autonomy/renew")
        assert renewed.status_code == 200 and renewed.json()["leaseUntil"] > before

        down = await api.post("/api/autonomy/disarm", {"target": "CONFIRM", "reason": "end of the session"})
        assert down.status_code == 200
        assert down.json()["mode"] == "CONFIRM" and down.json()["leaseUntil"] is None
        again = await api.post("/api/autonomy/disarm", {"target": "OBSERVE"})
        assert again.json()["mode"] == "OBSERVE"
        assert (await api.post("/api/autonomy/renew")).status_code == 409  # no lease to renew any more


async def test_disarming_to_a_higher_rung_is_a_no_op_not_a_climb(api: Api) -> None:
    response = await api.post("/api/autonomy/disarm", {"target": "AUTONOMOUS"})
    assert response.status_code == 200 and response.json()["mode"] == "OBSERVE"


# ------------------------------------------------------------------------------------------------------ the brake


async def test_the_emergency_stop_halts_tells_the_agent_and_locks_the_active_account(api: Api) -> None:
    response = await api.post("/api/autonomy/halt", {"reason": "test stop"})
    body = response.json()
    assert response.status_code == 200 and body["state"]["mode"] == "HALTED"
    assert "test stop" in body["state"]["haltedReason"]
    assert body["killSwitch"]["reason"] == "Kill switch manuel" and body["killSwitch"]["until"] is None
    assert body["warnings"] == []
    assert api.core.link.halts and api.core.link.halts[0][1] == "test stop"  # the execution agent was told to stop

    # the ledger agrees, and the account cannot trade
    ledger = (await api.get("/api/risk/lockouts")).json()
    assert ledger["active"]["lockoutId"] == body["killSwitch"]["lockoutId"]
    assert (await api.get("/api/risk/can-i-trade")).json()["decision"] == "DENIED"


async def test_halting_twice_is_halting_once(api: Api) -> None:
    first = (await api.post("/api/autonomy/halt", {})).json()
    second = (await api.post("/api/autonomy/halt", {"reason": "pressed again"})).json()
    assert second["state"]["haltedReason"] == first["state"]["haltedReason"]  # the first reason stands
    assert second["killSwitch"]["lockoutId"] == first["killSwitch"]["lockoutId"]  # one lockout, not two


async def test_a_halt_is_left_only_by_an_explicit_acknowledgement_and_lands_on_off(api: Api) -> None:
    await api.post("/api/autonomy/halt", {})
    assert (await api.post("/api/autonomy/arm", {"target": "PAPER"})).json()["code"] == "halted"
    refused = await api.post("/api/autonomy/disarm", {})
    assert refused.status_code == 403 and refused.json()["code"] == "ack_required"
    left = await api.post("/api/autonomy/disarm", {"acknowledge": True})
    assert left.status_code == 200 and left.json()["mode"] == "OFF"  # never straight back to trading


async def test_the_halt_stands_even_when_the_lockout_cannot_be_recorded(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(*args: object, **kwargs: object) -> None:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(api.core.c.repos.risk, "open_lockout", down)
    response = await api.post("/api/autonomy/halt", {})
    body = response.json()
    assert response.status_code == 200 and body["state"]["mode"] == "HALTED"  # the cut does not wait for the database
    assert body["killSwitch"] is None and "could not be recorded" in body["warnings"][0]


@pytest.mark.parametrize(
    "body", [{"reason": ""}, {"reason": "x" * 201}, {"why": "because"}], ids=["empty", "long", "field"]
)
async def test_a_malformed_halt_is_refused_before_anything_is_cut(api: Api, body: dict[str, Any]) -> None:
    assert (await api.post("/api/autonomy/halt", body)).status_code == 422
    assert await mode_of(api) == "OBSERVE"


async def test_a_clock_that_runs_does_not_arm_by_itself(api: Api) -> None:
    api.core.h.clock.advance(hours=3)
    await api.core.cycle()
    assert await mode_of(api) == "OBSERVE"  # nothing in the core climbs on its own
