"""Who may drive the core — the port of ``LocalAccessGuard.cs`` (I0, 2026-09-26), tightened as ADR 0016 asks: **reads too**.

Every request under ``/api`` and every WebSocket (``/ws``) must carry the cockpit token **and** an allowed Origin; the one
exception is ``GET /api/system/health``, which a launcher or a monitor can read without a browser.

Why both. CORS does not apply to WebSockets, so any web page open in the trader's browser could otherwise join the stream and
read it: the Origin check stops that — a browser always sends ``Origin`` on a handshake and a page cannot forge it. The token
stops clients that *can* forge headers: other containers reach ``127.0.0.1``-published ports through
``host.docker.internal``, and local processes reach them directly.

* **No token configured = every guarded request is refused** (fail closed), with a message that says what to do.
* The comparison is constant-time. A token can be presented as ``Authorization: Bearer …`` or — for a browser WebSocket, which
  cannot set headers — as ``?access_token=``.
* A request that presents two ``Origin`` headers (or two tokens) presents none.
* A refusal is logged on one line **without the query string**: the WebSocket token travels in it.

Limit, written down rather than hidden: the cockpit gets the token from the Next server (``app/api/cockpit-token``, which checks
the Host and ``Sec-Fetch-Site`` — a browser guard). A client that forges both against Next can read it, as can any process
running as the trader. The threat model is the network, browsers and generic container traffic — not targeted malware on this
machine (ADR 0013).

The decision is a pure function so it is tested without a server; the middleware is plain ASGI (not ``BaseHTTPMiddleware``) so
that the same code guards HTTP and WebSocket scopes.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Sequence
from enum import StrEnum
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

OPEN_PATHS = frozenset({"/api/system/health"})
_READS = frozenset({"GET", "HEAD"})


class Verdict(StrEnum):
    NOT_GUARDED = "not_guarded"
    ALLOWED = "allowed"
    NO_TOKEN_CONFIGURED = "no_token_configured"
    ORIGIN_REFUSED = "origin_refused"
    TOKEN_REFUSED = "token_refused"


REFUSALS = {
    Verdict.NO_TOKEN_CONFIGURED: (
        "Le cœur n'a pas de jeton du cockpit : TRADINGOS_COCKPIT_TOKEN manque dans .env "
        "(scripts/start-live.ps1 l'écrit) — relance le cœur après l'avoir ajouté."
    ),
    Verdict.ORIGIN_REFUSED: "Origine refusée : seul le cockpit local peut interroger le cœur.",
    Verdict.TOKEN_REFUSED: (
        "Jeton du cockpit refusé : le cockpit et le cœur n'ont pas le même TRADINGOS_COCKPIT_TOKEN — relance le cœur."
    ),
}


def refusal_message(verdict: Verdict) -> str:
    return REFUSALS.get(verdict, "Accès refusé.")


def _under(path: str, prefix: str) -> bool:
    lowered = path.lower()
    return lowered == prefix or lowered.startswith(prefix + "/")


def is_guarded(path: str, method: str) -> bool:
    """Whether the request is the cockpit's business. Anything else (``/``, a favicon) has nothing to protect: it has no route."""
    if _under(path, "/ws"):
        return True
    if not _under(path, "/api"):
        return False
    return not (path.lower().rstrip("/") in OPEN_PATHS and method.upper() in _READS)


def bearer_token(authorization: str | None) -> str | None:
    prefix = "Bearer "
    if authorization is not None and authorization.startswith(prefix):
        return authorization[len(prefix) :].strip()
    return None


def evaluate_access(
    path: str,
    method: str,
    origin: str | None,
    authorization: str | None,
    query_token: str | None,
    configured_token: str | None,
    allowed_origins: Sequence[str],
) -> Verdict:
    if not is_guarded(path, method):
        return Verdict.NOT_GUARDED
    if not configured_token:
        return Verdict.NO_TOKEN_CONFIGURED
    if origin is None or origin not in allowed_origins:
        return Verdict.ORIGIN_REFUSED
    presented = bearer_token(authorization)
    if presented is None:
        presented = query_token
    if presented is not None and hmac.compare_digest(presented.encode("utf-8"), configured_token.encode("utf-8")):
        return Verdict.ALLOWED
    return Verdict.TOKEN_REFUSED


def _single_header(scope: Scope, name: bytes) -> str | None:
    values = [value for key, value in scope.get("headers", []) if key.lower() == name]
    return values[0].decode("latin-1") if len(values) == 1 else None


def _query_token(scope: Scope) -> str | None:
    values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("access_token", [])
    return values[0] if len(values) == 1 else None


class AccessGuardMiddleware:
    """Applies ``evaluate_access`` to every HTTP and WebSocket request. Must sit *inside* the CORS middleware, so that a
    preflight is answered before it is judged and a refusal still carries the headers a browser needs to read it."""

    def __init__(self, app: ASGIApp, *, token: str | None, origins: Sequence[str]) -> None:
        self.app = app
        self._token = token
        self._origins = tuple(origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET") if scope["type"] == "http" else "GET"
        verdict = evaluate_access(
            scope["path"],
            method,
            _single_header(scope, b"origin"),
            _single_header(scope, b"authorization"),
            _query_token(scope),
            self._token,
            self._origins,
        )
        if verdict in (Verdict.NOT_GUARDED, Verdict.ALLOWED):
            await self.app(scope, receive, send)
            return
        logger.warning(
            "refused %s %s: %s", method, scope["path"], verdict.value
        )  # never the query string: it holds the token
        if scope["type"] == "websocket":
            await receive()  # the connect message; answering before accepting rejects the handshake (HTTP 403)
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse({"code": verdict.value, "message": refusal_message(verdict)}, status_code=403)
        await response(scope, receive, send)
