"""The system routes, the error envelope, CORS and the OpenAPI schema — the application as a browser would meet it."""

from __future__ import annotations

import pytest

from tests.support.api import ORIGIN, TOKEN, Api
from trading_os.shared.errors import Conflict

pytestmark = pytest.mark.db


# ------------------------------------------------------------------------------------------------------ health and guard


async def test_the_health_is_open_minimal_and_never_names_a_secret_or_an_account(api: Api) -> None:
    async with api.bare() as anonymous:
        response = await anonymous.get("/api/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["database"]["up"] is True and body["agentsConnected"] == 1
    assert body["access"] == {"cockpitGuarded": True, "agentLinkGuarded": False}  # whether, never what
    assert {job["name"] for job in body["jobs"]} == set() and body["websocket"]["clients"] == 0
    assert TOKEN not in response.text and "exness" not in response.text and "1000001" not in response.text
    assert set(body) >= {"version", "startedAt", "uptimeSeconds", "checkedAt", "audit", "ticks", "findings"}


async def test_everything_else_needs_the_token_and_the_origin(api: Api) -> None:
    async with api.bare() as anonymous:
        for path in ("/api/system/status", "/api/system/readiness", "/api/system/events", "/api/openapi.json"):
            refused = await anonymous.get(path)
            assert refused.status_code == 403 and refused.json()["code"] == "origin_refused", path
        wrong = await anonymous.get("/api/system/status", headers={"Origin": ORIGIN, "Authorization": "Bearer nope"})
        assert wrong.status_code == 403 and wrong.json()["code"] == "token_refused"


# ------------------------------------------------------------------------------------------------------ the overview


async def test_the_status_is_the_cockpits_overview_in_camel_case(api: Api) -> None:
    response = await api.get("/api/system/status")
    assert response.status_code == 200
    body = response.json()
    account = api.core.account
    assert account is not None
    assert body["activeAccountId"] == account.id and [a["id"] for a in body["accounts"]] == [account.id]
    assert body["accounts"][0]["status"] == "CONNECTED" and "password" not in response.text.lower()
    assert body["autonomy"]["state"]["mode"] == "OBSERVE" and body["autonomy"]["ceiling"] == "AUTONOMOUS"
    assert body["autonomy"]["effectiveMode"] == "OBSERVE"
    assert [a["agentId"] for a in body["agents"]] == ["mt5-execution-agent-7001"]
    assert body["health"]["status"] == "ok" and body["serverTime"].endswith("Z")


async def test_the_readiness_is_the_sixteen_checks(api: Api) -> None:
    response = await api.get("/api/system/readiness", fresh="true")
    body = response.json()
    assert response.status_code == 200 and body["ready"] is True and body["blockers"] == []
    assert len(body["checks"]) == 16 and {"checkId", "label", "ok", "detail"} <= set(body["checks"][0])


async def test_a_red_check_shows_in_the_readiness(api: Api) -> None:
    api.core.link.statuses.clear()
    body = (await api.get("/api/system/readiness", fresh="true")).json()
    assert body["ready"] is False and set(body["blockers"]) == {"kill_switch_available", "heartbeat"}


# ------------------------------------------------------------------------------------------------------ audit and incidents


async def test_the_audit_trail_serves_what_was_recorded_newest_first_and_filterable(api: Api) -> None:
    account = api.core.account
    assert account is not None
    everything = (await api.get("/api/system/events", limit=100)).json()
    assert everything, "creating and connecting the account was recorded"
    assert [e["occurredAt"] for e in everything] == sorted((e["occurredAt"] for e in everything), reverse=True)
    created = (await api.get("/api/system/events", types="account.created")).json()
    assert [e["type"] for e in created] == ["account.created"] and created[0]["accountId"] == account.id
    assert created[0]["payload"]["provider"] == "EXNESS"
    other = (await api.get("/api/system/events", accountId="no-such-account")).json()
    assert other == []
    limited = (await api.get("/api/system/events", limit=1)).json()
    assert len(limited) == 1


async def test_a_bad_query_is_a_validation_error_that_never_echoes_the_value(api: Api) -> None:
    response = await api.get("/api/system/events", limit=0)
    body = response.json()
    assert response.status_code == 422 and body["code"] == "validation_failed"
    assert body["details"]["errors"][0]["loc"] == ["query", "limit"] and "input" not in str(body)


async def test_incidents_are_listed_and_can_be_narrowed_to_the_open_ones(api: Api) -> None:
    assert (await api.get("/api/system/incidents")).json() == []
    core = api.core
    core.terminal.add_position(
        identifier=999, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099, magic=7001
    )
    core.h.clock.advance(seconds=2)
    await core.cycle()
    opened = (await api.get("/api/system/incidents", openOnly="true")).json()
    assert [i["code"] for i in opened] == ["unexpected_position"] and opened[0]["severity"] == "critical"
    assert opened[0]["resolvedAt"] is None
    assert len((await api.get("/api/system/incidents")).json()) == 1


# ------------------------------------------------------------------------------------------------------ the envelope


async def test_every_error_has_the_same_envelope(api: Api) -> None:
    missing = await api.get("/api/no/such/route")
    assert missing.status_code == 404 and missing.json() == {"code": "not_found", "message": "Not Found", "details": {}}
    wrong_method = await api.client.delete("/api/system/status")
    assert wrong_method.status_code == 405 and wrong_method.json()["code"] == "method_not_allowed"


async def test_a_core_error_carries_its_own_code_status_and_details(api: Api) -> None:
    async def conflict() -> None:
        raise Conflict("cannot do that now", code="not_now", details={"why": "because"})

    async def bug() -> None:
        raise RuntimeError("secret internals: password=hunter2")

    api.app.add_api_route("/api/test/conflict", conflict)
    api.app.add_api_route("/api/test/bug", bug)
    refused = await api.get("/api/test/conflict")
    assert refused.status_code == 409
    assert refused.json() == {"code": "not_now", "message": "cannot do that now", "details": {"why": "because"}}
    broken = await api.get("/api/test/bug")
    assert broken.status_code == 500 and broken.json() == {
        "code": "internal_error",
        "message": "internal error",
        "details": {},
    }
    assert "hunter2" not in broken.text and "RuntimeError" not in broken.text


# ------------------------------------------------------------------------------------------------------ CORS


async def test_a_preflight_is_answered_without_credentials_for_the_cockpit_only(api: Api) -> None:
    async with api.bare() as anonymous:
        ask = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}
        allowed = await anonymous.options("/api/system/status", headers={"Origin": ORIGIN, **ask})
        assert allowed.status_code == 200 and allowed.headers["access-control-allow-origin"] == ORIGIN
        assert "authorization" in allowed.headers["access-control-allow-headers"].lower()
        foreign = await anonymous.options("/api/system/status", headers={"Origin": "https://evil.example", **ask})
        assert "access-control-allow-origin" not in foreign.headers and foreign.status_code == 400


async def test_a_refusal_still_carries_the_headers_that_let_the_cockpit_read_it(api: Api) -> None:
    async with api.bare() as anonymous:
        refused = await anonymous.get("/api/system/status", headers={"Origin": ORIGIN, "Authorization": "Bearer nope"})
    assert refused.status_code == 403 and refused.headers["access-control-allow-origin"] == ORIGIN


# ------------------------------------------------------------------------------------------------------ OpenAPI


async def test_the_schema_is_served_under_the_guard_with_readable_operation_ids(api: Api) -> None:
    schema = (await api.get("/api/openapi.json")).json()
    assert schema["info"]["title"] == "Trading OS core"
    assert schema["paths"]["/api/system/health"]["get"]["operationId"] == "system_health"
    assert schema["paths"]["/api/system/events"]["get"]["operationId"] == "system_events"
    assert api.app.openapi()["paths"].keys() == schema["paths"].keys()
