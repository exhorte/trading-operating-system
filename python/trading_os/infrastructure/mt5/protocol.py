"""The contract between the core and the MT5 read worker: a **whitelist** of read-only functions, and JSON (de)serialisation.

This module is deliberately free of ``MetaTrader5``: the whitelist and the dispatcher are testable (and tested) without a
terminal, and the worker is the *only* module allowed to import the package. Nothing that opens, modifies or closes a
position, or even *checks* an order, is in ``ALLOWED_FUNCTIONS`` — a test fails if one ever appears. Orders leave the core
through the execution agent (``ea_link``) and nowhere else.

Arguments cross the pipe as JSON; two markers cover what JSON lacks:

* ``{"$dt": "<ISO 8601>"}`` → ``datetime`` (history functions take datetimes — in the **broker's** clock, see ``observer_logic``)
* ``{"$tf": "M15"}``        → the ``TIMEFRAME_M15`` constant of the package
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

# Everything the core may ask of a terminal. Read-only by construction.
ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "initialize",
        "login",
        "shutdown",
        "last_error",
        "version",
        "account_info",
        "terminal_info",
        "symbol_info",
        "symbol_info_tick",
        "symbol_select",
        "symbols_get",
        "symbols_total",
        "positions_get",
        "positions_total",
        "orders_get",
        "orders_total",
        "history_deals_get",
        "history_orders_get",
        "copy_rates_from_pos",
        "copy_rates_from",
        "copy_rates_range",
        "copy_ticks_from",
        "copy_ticks_range",
        "order_calc_margin",  # read-only calculators: they price a hypothetical order, they place nothing
        "order_calc_profit",
    }
)

# Fields dropped from results before they leave the worker. The account holder's name is personal data and every
# event the core publishes is persisted and immutable (ADR 0009).
STRIPPED_FIELDS: dict[str, frozenset[str]] = {"account_info": frozenset({"name"})}


class WorkerError(Exception):
    """A call failed inside the worker (the package raised, or the function is not allowed)."""

    def __init__(self, message: str, *, code: str = "exception") -> None:
        super().__init__(message)
        self.code = code


def to_jsonable(value: Any) -> Any:
    """Namedtuples (every MT5 info object), numpy structured arrays (rates/ticks), numpy scalars, tuples → JSON."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if hasattr(value, "_asdict"):
        return {key: to_jsonable(item) for key, item in value._asdict().items()}
    dtype = getattr(value, "dtype", None)
    names = getattr(dtype, "names", None)
    if names:  # a structured array: one dict per row
        return [{name: to_jsonable(row[name]) for name in names} for row in value]
    if hasattr(value, "tolist"):  # a numpy array or scalar
        return to_jsonable(value.tolist())
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return str(value)


def decode_argument(value: Any, module: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"$dt"}:
            return datetime.fromisoformat(value["$dt"])
        if set(value) == {"$tf"}:
            return getattr(module, f"TIMEFRAME_{value['$tf']}")
    if isinstance(value, list):
        return [decode_argument(item, module) for item in value]
    return value


def encode_argument(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    return value


def dispatch(module: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Execute one request against ``module`` (the real package or the fake). Never raises: errors are values."""
    request_id = request.get("id")
    name = request.get("fn")
    if not isinstance(name, str) or name not in ALLOWED_FUNCTIONS:
        return {"id": request_id, "ok": False, "code": "not_allowed", "error": f"function {name!r} is not allowed"}
    secret = _password_of(request)
    try:
        args = [decode_argument(arg, module) for arg in request.get("args", [])]
        kwargs = {key: decode_argument(arg, module) for key, arg in request.get("kwargs", {}).items()}
        function: Callable[..., Any] = getattr(module, name)
        result = to_jsonable(function(*args, **kwargs))
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        if secret:
            message = message.replace(secret, "***")
        return {"id": request_id, "ok": False, "code": "exception", "error": message}
    for field in STRIPPED_FIELDS.get(name, ()):
        if isinstance(result, dict):
            result.pop(field, None)
    return {"id": request_id, "ok": True, "result": result}


def _password_of(request: dict[str, Any]) -> str | None:
    kwargs = request.get("kwargs") or {}
    password = kwargs.get("password")
    if isinstance(password, str) and password:
        return password
    args = request.get("args") or []
    if request.get("fn") == "login" and len(args) >= 2 and isinstance(args[1], str):
        return args[1]
    return None


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), allow_nan=True)
