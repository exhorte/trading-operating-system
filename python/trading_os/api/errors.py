"""One error envelope for the whole API: ``{"code", "message", "details"}``, the status carried by the error itself.

* A ``TradingOsError`` is the core describing a condition it handles (« unavailable », « conflict », « forbidden » …): its
  stable ``code`` is what the cockpit and the tests switch on, its message has already been through the secret masker.
* A **validation error never echoes the value it rejected.** FastAPI's default 422 body quotes the offending input — on a
  route that takes a broker password that would put the password in a response (and in whatever logs it). Only where the
  problem is (``loc``), what it is (``msg``, ``type``) are returned.
* Anything else is a bug: logged with its traceback (masked), answered with a bare 500 that says nothing of the internals.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from trading_os.shared.errors import TradingOsError

logger = logging.getLogger(__name__)

_HTTP_CODES = {
    404: "not_found",
    405: "method_not_allowed",
    401: "unauthorized",
    403: "forbidden",
    422: "validation_failed",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TradingOsError)
    async def trading_os_error(request: Request, error: TradingOsError) -> JSONResponse:
        return JSONResponse(error.to_dict(), status_code=error.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        problems = [
            {"loc": [str(part) for part in e["loc"]], "msg": e["msg"], "type": e["type"]} for e in error.errors()
        ]
        return JSONResponse(
            {"code": "validation_failed", "message": "the request is not valid", "details": {"errors": problems}},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(error.status_code, "http_error")
        return JSONResponse({"code": code, "message": str(error.detail), "details": {}}, status_code=error.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.error("unhandled error on %s %s", request.method, request.url.path, exc_info=error)
        return JSONResponse({"code": "internal_error", "message": "internal error", "details": {}}, status_code=500)
