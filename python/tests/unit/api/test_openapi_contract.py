"""The API surface as a contract. The cockpit's types are generated from this document (migration phase 6), so a route cannot
appear, move, lose its guard or start accepting unknown fields without a test saying so — and no database is needed to say it."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from trading_os.app.config import Settings
from trading_os.app.main import create_app

HEALTH = ("GET", "/api/system/health")

SURFACE: frozenset[tuple[str, str]] = frozenset(
    {
        HEALTH,
        ("GET", "/api/system/status"), ("GET", "/api/system/readiness"), ("GET", "/api/system/events"),
        ("GET", "/api/system/incidents"),
        # accounts
        ("GET", "/api/accounts"), ("POST", "/api/accounts"),
        ("GET", "/api/accounts/{account_id}"), ("PATCH", "/api/accounts/{account_id}"),
        ("DELETE", "/api/accounts/{account_id}"), ("PUT", "/api/accounts/{account_id}/trading"),
        ("POST", "/api/accounts/{account_id}/connect"), ("POST", "/api/accounts/{account_id}/disconnect"),
        ("POST", "/api/accounts/{account_id}/reconnect"),
        ("GET", "/api/accounts/{account_id}/snapshot"), ("GET", "/api/accounts/{account_id}/positions"),
        ("GET", "/api/accounts/{account_id}/orders"),
        ("GET", "/api/accounts/{account_id}/profile"), ("GET", "/api/accounts/{account_id}/effective-policy"),
        ("GET", "/api/accounts/{account_id}/provider-loss"),
        ("GET", "/api/accounts/{account_id}/rules"), ("POST", "/api/accounts/{account_id}/rules"),
        ("POST", "/api/accounts/{account_id}/rules/{version_id}/cancel"), ("POST", "/api/accounts/rules-preview"), ("POST", "/api/accounts/discover"),
        ("GET", "/api/accounts/{account_id}/credentials"), ("PUT", "/api/accounts/{account_id}/credentials"),
        ("DELETE", "/api/accounts/{account_id}/credentials"),
        ("GET", "/api/active-account"), ("PUT", "/api/active-account"),
        # autonomy
        ("GET", "/api/autonomy/state"), ("POST", "/api/autonomy/arm"), ("POST", "/api/autonomy/renew"),
        ("POST", "/api/autonomy/disarm"), ("POST", "/api/autonomy/halt"),
        ("GET", "/api/autonomy/promotion"), ("GET", "/api/why-no-trade"), ("GET", "/api/guardian"),  # ADR 0025, 0027, 0028
        # risk
        ("GET", "/api/risk/state"), ("GET", "/api/risk/can-i-trade"), ("POST", "/api/risk/evaluate"),
        ("GET", "/api/risk/decisions"), ("GET", "/api/risk/decisions/{decision_id}"),
        ("GET", "/api/risk/lockouts"), ("POST", "/api/risk/lockouts"),
        ("POST", "/api/risk/lockouts/{lockout_id}/acknowledge"),
        # execution
        ("GET", "/api/execution/state"), ("GET", "/api/execution/commands"), ("POST", "/api/execution/commands"),
        ("GET", "/api/execution/commands/{command_id}"), ("POST", "/api/execution/commands/{command_id}/confirm"),
        ("POST", "/api/execution/commands/{command_id}/cancel"),
        ("GET", "/api/execution/reconciliation"), ("POST", "/api/execution/reconciliation/run"),
        # close all positions (ADR 0034): a preview, one human gesture that submits ordinary CLOSE commands, and the follow-up of the batch
        ("GET", "/api/execution/close-all/preview"), ("POST", "/api/execution/close-all"),
        ("GET", "/api/execution/close-all/{batch_id}"), ("POST", "/api/execution/close-all/{batch_id}/verify"),
        # start-up of the trading system (ADR 0034): the stages, « start » (never above CONFIRM), and the separate automatic-trading gesture
        ("GET", "/api/system/startup"), ("POST", "/api/system/startup"),
        ("POST", "/api/system/startup/authorize-automatic"),
        # live measures (ADR 0035, L1): read-only
        ("GET", "/api/system/live-metrics"),
        # market
        ("GET", "/api/market/calendar"), ("GET", "/api/market/quotes"), ("GET", "/api/market/{symbol}"),
        ("GET", "/api/market/{symbol}/candles"), ("GET", "/api/market/{symbol}/context"),
        # journal
        ("GET", "/api/journal/trades"), ("GET", "/api/journal/compliance"),
        ("GET", "/api/journal/trades/{broker_position_id}"), ("GET", "/api/journal/captures/{broker_position_id}"),
        # strategy
        ("GET", "/api/strategy/proposals"), ("GET", "/api/strategy/intents"), ("GET", "/api/strategy/agreement"),
    }
)  # fmt: skip
# (the commands have no "execute" shortcut: an order is a command that went through a risk decision, and only the EA ever sends it.)

FORBIDDEN_WORDS = re.compile(r"order[-_/]?send|place[-_]?order|execute[-_]?trade|close[-_]?all", re.IGNORECASE)
# The one family that carries a forbidden word on purpose (ADR 0034, EA-08 « fermeture globale »): « close-all » is not a shortcut to an
# order — it builds ordinary CLOSE commands (a deterministic id each) and submits them to the execution engine as a human exit, so every
# one is persisted before it is sent, replayed rather than executed twice, and reconciled. Anything else with such a word stays refused.
CLOSE_ALL_FAMILY = frozenset(
    {
        ("GET", "/api/execution/close-all/preview"), ("POST", "/api/execution/close-all"),
        ("GET", "/api/execution/close-all/{batch_id}"), ("POST", "/api/execution/close-all/{batch_id}/verify"),
    }
)  # fmt: skip


def make_settings(token: str | None = None) -> Settings:
    settings = Settings(_env_file=None, database_url=SecretStr("postgresql://nobody@127.0.0.1:1/none"))
    if token is not None:
        settings.trading_os_cockpit_token = SecretStr(token)  # (read by alias only: assigned after construction)
    return settings


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    document: dict[str, Any] = create_app(make_settings(), start_engine=False).openapi()
    return document


def operations(document: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    methods = {"get", "post", "put", "patch", "delete"}
    return [
        (method.upper(), path, operation)
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in methods
    ]


# ------------------------------------------------------------------------------------------------------ the surface


def test_the_surface_is_exactly_the_documented_one(document: dict[str, Any]) -> None:
    found = {(method, path) for method, path, _ in operations(document)}
    assert found - SURFACE == set(), "undocumented routes: add them to SURFACE on purpose"
    assert SURFACE - found == set(), "documented routes that no longer exist"


def test_no_route_offers_a_shortcut_to_an_order(document: dict[str, Any]) -> None:
    offenders = [
        f"{m} {p}" for m, p, _ in operations(document) if FORBIDDEN_WORDS.search(p) and (m, p) not in CLOSE_ALL_FAMILY
    ]
    assert not offenders, offenders  # an order exists only as a command that went through a risk decision


def test_operation_ids_are_unique_and_readable(document: dict[str, Any]) -> None:
    ids = [operation["operationId"] for _, _, operation in operations(document)]
    assert len(ids) == len(set(ids)), "duplicate operation ids"
    assert all(re.fullmatch(r"[a-z]+_[a-z_]+", i) for i in ids), [
        i for i in ids if not re.fullmatch(r"[a-z]+_[a-z_]+", i)
    ]


def test_every_operation_is_tagged_and_summarised_or_self_evident(document: dict[str, Any]) -> None:
    for method, path, operation in operations(document):
        assert operation.get("tags"), f"{method} {path} has no tag"


def refs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        if "$ref" in node:
            found.add(str(node["$ref"]).rsplit("/", 1)[-1])
        for value in node.values():
            found |= refs(value)
    elif isinstance(node, list):
        for item in node:
            found |= refs(item)
    return found


def test_every_request_body_refuses_unknown_fields(document: dict[str, Any]) -> None:
    components = document["components"]["schemas"]
    lenient = []
    for method, path, operation in operations(document):
        body = operation.get("requestBody")
        if body is None:
            continue
        for name in refs(body):
            if components[name].get("additionalProperties") is not False:
                lenient.append(f"{method} {path}: {name}")
    assert not lenient, "request bodies must refuse unknown fields (a typo must not become a default):\n" + "\n".join(
        lenient
    )


def test_request_models_are_named_as_such(document: dict[str, Any]) -> None:
    components = document["components"]["schemas"]
    misnamed = []
    for method, path, operation in operations(document):
        if "requestBody" in operation:
            misnamed += [
                f"{method} {path}: {name}" for name in refs(operation["requestBody"]) if not name.endswith("Request")
            ]
    assert not misnamed, misnamed
    assert components  # (the generated types will carry these names)


# ------------------------------------------------------------------------------------------------------ the guard


@pytest.fixture
async def anonymous() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(token="contract-test-token-0123456789"), start_engine=False)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        yield client


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


@pytest.mark.parametrize("method,path", sorted(SURFACE - {HEALTH}))
async def test_every_route_but_the_health_refuses_a_caller_with_no_credentials(
    anonymous: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await anonymous.request(method, concrete(path))
    assert response.status_code == 403, f"{method} {path} answered {response.status_code} to a stranger"
    assert response.json()["code"] in {"origin_refused", "token_refused"}


@pytest.mark.parametrize("method,path", sorted(SURFACE - {HEALTH}))
async def test_a_known_origin_alone_is_not_enough(anonymous: httpx.AsyncClient, method: str, path: str) -> None:
    response = await anonymous.request(method, concrete(path), headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 403 and response.json()["code"] == "token_refused", f"{method} {path}"
