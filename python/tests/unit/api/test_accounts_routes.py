"""The accounts routes: the registry, the connection (and the password that must never come back out), the active account, the
versioned rules, the write-only vault."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import pytest

from tests.support.api import Api, create_second, make_api, new_account
from tests.support.core import MemoryCredentialStore
from tests.support.harness import Harness

pytestmark = pytest.mark.db

SENTINEL = "S3NTINEL-must-never-leave-this-request-7f3a"


@pytest.fixture
async def vault() -> MemoryCredentialStore:
    return MemoryCredentialStore()


@pytest.fixture
async def api(h: Harness, vault: MemoryCredentialStore) -> AsyncIterator[Api]:
    instance = await make_api(h, credentials=vault)
    yield instance
    await instance.close()


async def everything_the_api_says(api: Api) -> str:
    """Every place a leaked secret could surface after a request: the overview, the account list, the audit trail."""
    parts = [
        (await api.get("/api/system/status")).text,
        (await api.get("/api/accounts")).text,
        (await api.get("/api/system/events", limit=500)).text,
        (await api.get("/api/system/incidents")).text,
    ]
    return "\n".join(parts)


# ------------------------------------------------------------------------------------------------------ the registry


async def test_the_registry_lists_gets_creates_and_archives(api: Api) -> None:
    first = api.core.account
    assert first is not None
    listed = (await api.get("/api/accounts")).json()
    assert [a["id"] for a in listed] == [first.id] and listed[0]["status"] == "CONNECTED"
    assert (await api.get(f"/api/accounts/{first.id}")).json()["login"] == first.login

    created = await create_second(api)
    assert created["id"] == "exness-1000002" and created["status"] == "DISCONNECTED" and created["symbolSuffix"] == "m"
    assert created["riskProfile"]["drawdown"]["referenceBalance"] == 10_000 and created["tradingEnabled"] is True

    assert (await api.client.delete("/api/accounts/exness-1000002")).status_code == 204
    assert [a["id"] for a in (await api.get("/api/accounts")).json()] == [first.id]


async def test_an_unknown_account_is_a_404_with_the_standard_envelope(api: Api) -> None:
    for response in (await api.get("/api/accounts/nope"), await api.get("/api/accounts/nope/positions")):
        assert response.status_code == 404 and response.json()["code"].endswith("not_found")


async def test_a_malformed_registration_is_a_validation_error_naming_the_field(api: Api) -> None:
    response = await api.post("/api/accounts", {"name": "x"})
    body = response.json()
    assert response.status_code == 422 and body["code"] == "validation_failed"
    assert {error["loc"][-1] for error in body["details"]["errors"]} >= {"provider", "login", "server"}
    existing = api.core.account
    assert existing is not None
    duplicate = await api.post("/api/accounts", new_account(existing.login))
    assert duplicate.status_code == 409, duplicate.text


async def test_renaming_is_free_but_the_terminal_cannot_change_under_a_connection(api: Api) -> None:
    account = api.core.account
    assert account is not None
    renamed = await api.client.patch(f"/api/accounts/{account.id}", json={"name": "Main demo"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Main demo"
    moved = await api.client.patch(f"/api/accounts/{account.id}", json={"terminalPath": "C:/elsewhere"})
    assert moved.status_code == 409 and moved.json()["code"] == "account_connected"


async def test_the_trading_switch_is_a_put(api: Api) -> None:
    account = api.core.account
    assert account is not None
    off = await api.put(f"/api/accounts/{account.id}/trading", {"enabled": False})
    assert off.status_code == 200 and off.json()["tradingEnabled"] is False
    assert (await api.put(f"/api/accounts/{account.id}/trading", {"enabled": "maybe"})).status_code == 422


# ------------------------------------------------------------------------------------------------------ the connection


async def test_connect_and_disconnect_attach_and_detach_the_terminal(api: Api) -> None:
    await create_second(api)
    connected = await api.post("/api/accounts/exness-1000002/connect")
    assert connected.status_code == 200 and connected.json()["status"] == "CONNECTED"
    again = await api.post("/api/accounts/exness-1000002/connect")  # connecting twice is harmless
    assert again.status_code == 200
    detached = await api.post("/api/accounts/exness-1000002/disconnect")
    assert detached.status_code == 200 and detached.json()["status"] == "DISCONNECTED"
    # the first account stayed the active one throughout
    assert (await api.get("/api/active-account")).json() == {"accountId": api.core.account.id}  # type: ignore[union-attr]


async def test_disconnecting_is_refused_while_risk_is_open_and_forcing_is_explicit(api: Api) -> None:
    account = api.core.account
    assert account is not None
    api.core.terminal.add_position(
        identifier=777, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099, magic=0
    )
    await api.core.c.positions.poll(account.id)
    refused = await api.post(f"/api/accounts/{account.id}/disconnect")
    body = refused.json()
    assert refused.status_code == 409 and body["code"] == "disconnect_refused"
    assert any("open position" in reason for reason in body["details"]["reasons"])
    forced = await api.post(f"/api/accounts/{account.id}/disconnect", force="true")
    assert forced.status_code == 200 and forced.json()["status"] == "DISCONNECTED"


async def test_what_the_account_holds_is_served_from_the_cores_state(api: Api) -> None:
    account = api.core.account
    assert account is not None
    api.core.terminal.add_position(identifier=778, symbol="EURUSDm", side=1, volume=0.02, price_open=1.1, magic=0)
    await api.core.c.positions.poll(account.id)
    snapshot = (await api.get(f"/api/accounts/{account.id}/snapshot")).json()
    assert snapshot["balance"] == 10_000 and snapshot["accountId"] == account.id
    positions = (await api.get(f"/api/accounts/{account.id}/positions")).json()
    assert [(p["positionId"], p["side"], p["volume"]) for p in positions] == [("778", "sell", 0.02)]
    assert (await api.get(f"/api/accounts/{account.id}/orders")).json() == []


async def test_a_disconnected_account_has_no_snapshot_yet_and_says_so(api: Api) -> None:
    await create_second(api)
    response = await api.get("/api/accounts/exness-1000002/snapshot")
    assert response.status_code == 404 and response.json()["code"] == "no_snapshot"
    assert (await api.get("/api/accounts/exness-1000002/positions")).json() == []


# ------------------------------------------------------------------------------------------------------ the password


async def test_a_wrong_password_is_a_clear_refusal_that_does_not_contain_it(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    await create_second(api)
    with caplog.at_level(logging.DEBUG):
        response = await api.post("/api/accounts/exness-1000002/connect", {"password": SENTINEL})
    assert response.status_code == 502 and response.json()["code"] == "login_failed"
    assert SENTINEL not in response.text and SENTINEL not in caplog.text
    assert SENTINEL not in await everything_the_api_says(
        api
    )  # the error event the core published, the status, the audit
    assert (await api.get("/api/accounts/exness-1000002")).json()["status"] == "ERROR"


async def test_a_right_password_connects_and_is_kept_nowhere(api: Api, caplog: pytest.LogCaptureFixture) -> None:
    await create_second(api)
    with caplog.at_level(logging.DEBUG):
        response = await api.post("/api/accounts/exness-1000002/connect", {"password": "pw-1000002"})
    assert response.status_code == 200 and response.json()["status"] == "CONNECTED"
    assert "pw-1000002" not in response.text and "pw-1000002" not in caplog.text
    assert "pw-1000002" not in await everything_the_api_says(api)
    assert api.core.c.credentials.name == "memory" and not await api.core.c.credentials.has("exness-1000002")


async def test_a_validation_error_on_a_secret_route_never_echoes_what_was_sent(api: Api) -> None:
    await create_second(api)
    for body in ({"password": 12345, "bogus": SENTINEL}, {"password": SENTINEL, "extra": "x"}, {"pwd": SENTINEL}):
        response = await api.post("/api/accounts/exness-1000002/connect", body)
        assert response.status_code == 422 and SENTINEL not in response.text, body
    assert (await api.put("/api/accounts/exness-1000002/credentials", {"password": ""})).status_code == 422


# ------------------------------------------------------------------------------------------------------ the vault


async def test_the_vault_is_write_only(api: Api, vault: MemoryCredentialStore) -> None:
    await create_second(api)
    status = (await api.get("/api/accounts/exness-1000002/credentials")).json()
    assert status == {"store": "memory", "stored": False}
    stored = await api.put("/api/accounts/exness-1000002/credentials", {"password": SENTINEL})
    assert stored.status_code == 204 and stored.content == b"" and SENTINEL not in stored.text
    assert (await api.get("/api/accounts/exness-1000002/credentials")).json() == {"store": "memory", "stored": True}
    assert vault.secrets["exness-1000002"].get_secret_value() == SENTINEL  # held there, for the connection to use
    assert SENTINEL not in await everything_the_api_says(api)
    assert (await api.client.delete("/api/accounts/exness-1000002/credentials")).status_code == 204
    assert (await api.get("/api/accounts/exness-1000002/credentials")).json()["stored"] is False


async def test_the_default_vault_stores_nothing_and_says_why(h: Harness) -> None:
    default = await make_api(h)  # CREDENTIAL_STORE=none
    try:
        await create_second(default)
        refused = await default.put("/api/accounts/exness-1000002/credentials", {"password": SENTINEL})
        assert refused.status_code == 403 and refused.json()["code"] == "credential_store_disabled"
        assert SENTINEL not in refused.text
    finally:
        await default.close()


async def test_a_stored_password_is_used_by_the_connection(api: Api, vault: MemoryCredentialStore) -> None:
    await create_second(api)
    await api.put("/api/accounts/exness-1000002/credentials", {"password": "pw-1000002"})
    response = await api.post(
        "/api/accounts/exness-1000002/connect"
    )  # no password in the request: the vault supplies it
    assert response.status_code == 200 and response.json()["status"] == "CONNECTED"


# ------------------------------------------------------------------------------------------------------ the active account


async def test_the_active_account_is_one_and_only_a_connected_one(api: Api) -> None:
    first = api.core.account
    assert first is not None
    await create_second(api)
    refused = await api.put("/api/active-account", {"accountId": "exness-1000002"})
    assert refused.status_code == 409 and refused.json()["code"] == "account_not_connected"
    await api.post("/api/accounts/exness-1000002/connect")
    switched = await api.put("/api/active-account", {"accountId": "exness-1000002"})
    assert switched.status_code == 200 and switched.json() == {"accountId": "exness-1000002"}
    assert (await api.get("/api/system/status")).json()["activeAccountId"] == "exness-1000002"
    assert (await api.put("/api/active-account", {"accountId": first.id})).status_code == 200


async def test_the_active_account_cannot_be_switched_away_from_while_it_holds_risk(api: Api) -> None:
    first = api.core.account
    assert first is not None
    await create_second(api)
    await api.post("/api/accounts/exness-1000002/connect")
    api.core.terminal.add_position(
        identifier=779, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099, magic=0
    )
    await api.core.c.positions.poll(first.id)
    refused = await api.put("/api/active-account", {"accountId": "exness-1000002"})
    assert refused.status_code == 409 and refused.json()["code"] == "switch_refused"
    assert (await api.get("/api/active-account")).json() == {"accountId": first.id}


# ------------------------------------------------------------------------------------------------------ versioned rules


async def test_new_rules_apply_at_once_when_no_session_is_in_progress(api: Api) -> None:
    account = api.core.account
    assert account is not None
    overview = (await api.get(f"/api/accounts/{account.id}/rules")).json()
    rules = overview["resolution"]["rules"]
    rules["riskProfile"]["maxRiskPerTradePercent"] = 0.5
    api.core.h.clock.advance(seconds=5)
    created = await api.post(f"/api/accounts/{account.id}/rules", rules)
    assert created.status_code == 201 and created.json()["deferred"] is False
    after = (await api.get(f"/api/accounts/{account.id}/rules")).json()
    assert after["resolution"]["rules"]["riskProfile"]["maxRiskPerTradePercent"] == 0.5
    assert len(after["versions"]) >= 2


async def test_a_change_made_mid_session_waits_for_the_next_trading_day_and_can_be_withdrawn(api: Api) -> None:
    account = api.core.account
    assert account is not None
    api.core.terminal.add_position(
        identifier=780, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099, magic=0
    )
    await api.core.c.positions.poll(account.id)  # a position is open: a session is in progress
    rules = (await api.get(f"/api/accounts/{account.id}/rules")).json()["resolution"]["rules"]
    rules["riskProfile"]["maxRiskPerTradePercent"] = 5.0  # the exact move the anti-tilt rule exists to stop
    api.core.h.clock.advance(seconds=5)
    created = (await api.post(f"/api/accounts/{account.id}/rules", rules)).json()
    assert created["deferred"] is True and created["deferralReasons"][0]["code"] == "open_positions"
    in_force = (await api.get(f"/api/accounts/{account.id}/rules")).json()["resolution"]
    assert in_force["rules"]["riskProfile"]["maxRiskPerTradePercent"] != 5.0
    assert in_force["pending"]["versionId"] == created["versionId"]

    wrong_account = await api.post(f"/api/accounts/nope/rules/{created['versionId']}/cancel")
    assert wrong_account.status_code == 404
    cancelled = await api.post(f"/api/accounts/{account.id}/rules/{created['versionId']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json() == {"outcome": "cancelled"}
    assert (await api.get(f"/api/accounts/{account.id}/rules")).json()["resolution"]["pending"] is None


async def test_withdrawing_a_version_that_is_not_the_accounts_is_not_found(api: Api) -> None:
    account = api.core.account
    assert account is not None
    response = await api.post(f"/api/accounts/{account.id}/rules/rules-unknown/cancel")
    assert response.status_code == 404 and response.json()["code"] == "rule_version_not_found"


async def test_nothing_in_the_openapi_schema_lets_a_secret_come_back(api: Api) -> None:
    schema = (await api.get("/api/openapi.json")).json()
    components = schema["components"]["schemas"]
    for name, model in components.items():
        for field, definition in model.get("properties", {}).items():
            if "password" in field.lower():
                assert (name.endswith("Request") and definition.get("writeOnly") is True) or any(
                    option.get("writeOnly") for option in definition.get("anyOf", [])
                ), (name, field)
    assert "password" not in json.dumps(schema["paths"]["/api/accounts"]["get"]).lower()
