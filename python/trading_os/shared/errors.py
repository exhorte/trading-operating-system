"""Typed errors. Each carries a stable machine ``code`` (what the cockpit and tests switch on)
and an HTTP status for the API layer. Messages never contain secrets: ``redact`` is applied on the way out."""

from __future__ import annotations

from typing import Any

from trading_os.shared.logging.redaction import redact


class TradingOsError(Exception):
    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str = "", *, code: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.details = details or {}

    @property
    def safe_message(self) -> str:
        return redact(str(self))

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.safe_message, "details": self.details}


class ValidationFailed(TradingOsError):
    code = "validation_failed"
    http_status = 422


class NotFound(TradingOsError):
    code = "not_found"
    http_status = 404


class Conflict(TradingOsError):
    code = "conflict"
    http_status = 409


class Forbidden(TradingOsError):
    code = "forbidden"
    http_status = 403


class Unavailable(TradingOsError):
    """A dependency the operation needs is down (database, MT5, agent). Fail closed."""

    code = "unavailable"
    http_status = 503


class AccountMismatch(TradingOsError):
    """A command or connection targets another account than the one really attached (ADR 0010)."""

    code = "account_mismatch"
    http_status = 409


class RiskRejected(TradingOsError):
    code = "risk_rejected"
    http_status = 409


class SizingError(TradingOsError):
    """Position size cannot be derived safely (missing symbol specs, stop too tight, minimum lot over budget)."""

    code = "sizing_error"
    http_status = 422


class IllegalTransition(TradingOsError):
    """A state machine was asked for a transition its table does not contain."""

    code = "illegal_transition"
    http_status = 409
