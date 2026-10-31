"""The access guard: the cockpit's token AND an allowed Origin, on every request but one — and fail closed otherwise. Reads are guarded
too (ADR 0016), not only writes."""

from __future__ import annotations

import logging

import httpx
import pytest
from starlette.types import Message, Receive, Scope, Send

from trading_os.api.security import (
    AccessGuardMiddleware,
    Verdict,
    bearer_token,
    evaluate_access,
    is_guarded,
    refusal_message,
)

TOKEN = "s3cret-token_value"
ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def judge(
    path: str,
    method: str = "GET",
    origin: str | None = "http://localhost:3000",
    authorization: str | None = None,
    query_token: str | None = TOKEN,
    configured: str | None = TOKEN,
) -> Verdict:
    return evaluate_access(path, method, origin, authorization, query_token, configured, ORIGINS)


class TestDecision:
    def test_the_socket_opens_with_the_token_and_an_allowed_origin(self) -> None:
        assert judge("/ws") is Verdict.ALLOWED
        assert judge("/ws", query_token=None, authorization=f"Bearer {TOKEN}") is Verdict.ALLOWED

    def test_a_foreign_web_page_is_refused_even_with_the_token(self) -> None:
        # CORS does not apply to WebSockets: the Origin check is what stops a page on another site.
        for origin in ("https://evil.example", "http://localhost:3000.evil.example", "null", "http://localhost:3001"):
            assert judge("/ws", origin=origin) is Verdict.ORIGIN_REFUSED, origin

    def test_a_client_without_an_origin_is_refused(self) -> None:
        assert (
            judge("/ws", origin=None) is Verdict.ORIGIN_REFUSED
        )  # curl from a container sends none; the cockpit always does
        assert judge("/api/accounts", origin=None, query_token=None, authorization=f"Bearer {TOKEN}") is (
            Verdict.ORIGIN_REFUSED
        )

    def test_a_wrong_or_missing_token_is_refused(self) -> None:
        assert judge("/ws", query_token=None) is Verdict.TOKEN_REFUSED
        assert judge("/ws", query_token="s3cret-token_valuE") is Verdict.TOKEN_REFUSED
        assert judge("/ws", query_token=TOKEN + "x") is Verdict.TOKEN_REFUSED
        assert judge("/ws", query_token=None, authorization=TOKEN) is Verdict.TOKEN_REFUSED  # no « Bearer »
        assert judge("/ws", query_token=None, authorization="Basic " + TOKEN) is Verdict.TOKEN_REFUSED
        assert judge("/ws", query_token=None, authorization="Bearer ") is Verdict.TOKEN_REFUSED

    def test_no_configured_token_refuses_everything_guarded(self) -> None:
        for configured in (None, ""):
            assert judge("/ws", configured=configured) is Verdict.NO_TOKEN_CONFIGURED
            assert judge("/api/accounts", configured=configured) is Verdict.NO_TOKEN_CONFIGURED
        assert judge("/ws", configured="", query_token="") is Verdict.NO_TOKEN_CONFIGURED

    def test_every_path_under_the_socket_and_the_api_is_guarded_whatever_the_case(self) -> None:
        assert judge("/ws/anything", query_token=None) is Verdict.TOKEN_REFUSED
        assert judge("/WS", origin=None) is Verdict.ORIGIN_REFUSED
        assert judge("/API/accounts", origin=None) is Verdict.ORIGIN_REFUSED

    def test_in_the_api_reads_are_guarded_too_unlike_the_old_backend(self) -> None:
        assert judge("/api/accounts", origin=None, query_token=None) is Verdict.ORIGIN_REFUSED
        assert judge("/api/risk/state", method="HEAD", origin=None, query_token=None) is Verdict.ORIGIN_REFUSED
        assert judge("/api/accounts", method="POST", query_token=None) is Verdict.TOKEN_REFUSED
        assert (
            judge("/api/accounts", method="POST", query_token=None, authorization=f"Bearer {TOKEN}") is Verdict.ALLOWED
        )
        assert judge("/api/openapi.json", origin=None) is Verdict.ORIGIN_REFUSED

    def test_only_the_health_read_is_open(self) -> None:
        assert judge("/api/system/health", origin=None, query_token=None, configured=None) is Verdict.NOT_GUARDED
        assert judge("/api/system/health/", method="HEAD", origin=None, query_token=None) is Verdict.NOT_GUARDED
        assert (
            judge("/api/system/health", method="POST", query_token=None) is Verdict.TOKEN_REFUSED
        )  # a write is not a read
        assert judge("/api/system/status", origin=None) is Verdict.ORIGIN_REFUSED  # its neighbours are guarded

    def test_what_is_not_under_the_api_or_the_socket_is_not_the_cockpits_business(self) -> None:
        for path in ("/", "/favicon.ico", "/apixyz", "/wsx", "/docs"):
            assert judge(path, method="POST", origin=None, query_token=None) is Verdict.NOT_GUARDED, path

    def test_a_bearer_token_is_trimmed_and_prefix_exact(self) -> None:
        assert bearer_token(f"Bearer  {TOKEN} ") == TOKEN and bearer_token("bearer " + TOKEN) is None
        assert bearer_token(None) is None and is_guarded("/ws", "GET")

    def test_a_refusal_never_contains_a_token(self) -> None:
        for verdict in (Verdict.NO_TOKEN_CONFIGURED, Verdict.ORIGIN_REFUSED, Verdict.TOKEN_REFUSED):
            assert TOKEN not in refusal_message(verdict) and refusal_message(verdict)


# ------------------------------------------------------------------------------------------------------ the middleware


async def inner_app(scope: Scope, receive: Receive, send: Send) -> None:
    """What the guard protects: it records that it was reached and answers 200 / accepts the socket."""
    inner_app.reached = True  # type: ignore[attr-defined]
    if scope["type"] == "websocket":
        await receive()
        await send({"type": "websocket.accept"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"reached"})


def guarded(token: str | None = TOKEN) -> httpx.AsyncClient:
    inner_app.reached = False  # type: ignore[attr-defined]
    app = AccessGuardMiddleware(inner_app, token=token, origins=ORIGINS)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000")


async def test_a_refused_request_gets_403_with_a_reason_and_never_reaches_the_app() -> None:
    async with guarded() as client:
        for headers, code in (
            ({"Origin": "https://evil.example", "Authorization": f"Bearer {TOKEN}"}, "origin_refused"),
            ({"Origin": "http://localhost:3000", "Authorization": "Bearer wrong"}, "token_refused"),
            ({"Authorization": f"Bearer {TOKEN}"}, "origin_refused"),
        ):
            response = await client.get("/api/accounts", headers=headers)
            assert response.status_code == 403 and response.json()["code"] == code
            assert response.json()["message"] and TOKEN not in response.text
        assert inner_app.reached is False  # type: ignore[attr-defined]


async def test_the_cockpit_gets_through_by_header_or_by_query_token() -> None:
    async with guarded() as client:
        ok = await client.get(
            "/api/accounts", headers={"Origin": "http://127.0.0.1:3000", "Authorization": f"Bearer {TOKEN}"}
        )
        assert ok.status_code == 200 and ok.text == "reached"
        via_query = await client.get(f"/ws?access_token={TOKEN}", headers={"Origin": "http://localhost:3000"})
        assert via_query.status_code == 200


async def test_without_a_configured_token_everything_guarded_is_refused_and_the_health_stays_open() -> None:
    async with guarded(token=None) as client:
        refused = await client.get(
            "/api/accounts", headers={"Origin": "http://localhost:3000", "Authorization": "Bearer x"}
        )
        assert refused.status_code == 403 and refused.json()["code"] == "no_token_configured"
        health = await client.get("/api/system/health")
        assert health.status_code == 200


async def test_two_origin_headers_are_not_an_origin() -> None:
    async with guarded() as client:
        response = await client.get(
            "/api/accounts",
            headers=[
                ("Origin", "http://localhost:3000"),
                ("Origin", "https://evil.example"),
                ("Authorization", f"Bearer {TOKEN}"),
            ],
        )
        assert response.status_code == 403 and inner_app.reached is False  # type: ignore[attr-defined]


async def test_two_query_tokens_are_not_a_token() -> None:
    async with guarded() as client:
        response = await client.get(
            f"/ws?access_token={TOKEN}&access_token={TOKEN}", headers={"Origin": "http://localhost:3000"}
        )
        assert response.status_code == 403


async def test_a_websocket_handshake_is_rejected_before_it_is_accepted() -> None:
    app = AccessGuardMiddleware(inner_app, token=TOKEN, origins=ORIGINS)
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "websocket", "path": "/ws", "query_string": b"access_token=wrong",
        "headers": [(b"origin", b"http://localhost:3000")],
    }  # fmt: skip
    inner_app.reached = False  # type: ignore[attr-defined]
    await app(scope, receive, send)
    assert sent == [{"type": "websocket.close", "code": 1008}] and inner_app.reached is False  # type: ignore[attr-defined]

    ok_scope = {**scope, "query_string": f"access_token={TOKEN}".encode()}
    sent.clear()
    await app(ok_scope, receive, send)
    assert sent == [{"type": "websocket.accept"}] and inner_app.reached is True  # type: ignore[attr-defined]


async def test_lifespan_and_other_scopes_pass_straight_through() -> None:
    app = AccessGuardMiddleware(inner_app, token=None, origins=ORIGINS)
    inner_app.reached = False  # type: ignore[attr-defined]

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(message: Message) -> None:
        return None

    await app({"type": "lifespan"}, receive, send)
    assert inner_app.reached is True  # type: ignore[attr-defined]


async def test_a_refusal_is_logged_without_the_query_string(caplog: pytest.LogCaptureFixture) -> None:
    secret = "a-token-that-must-never-be-logged"
    async with guarded() as client:
        with caplog.at_level(logging.WARNING, logger="trading_os.api.security"):
            await client.get(f"/ws?access_token={secret}", headers={"Origin": "https://evil.example"})
    assert (
        "refused GET /ws: origin_refused" in caplog.text
        and secret not in caplog.text
        and "access_token" not in caplog.text
    )
