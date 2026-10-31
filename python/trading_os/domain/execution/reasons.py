"""Typed rejection vocabulary of the execution path (ADR 0010). A rejection is a value with a stable code — the cockpit
and the audit trail switch on the code, never on prose."""

from __future__ import annotations

from enum import StrEnum

from trading_os.domain.primitives import DomainModel


class RejectCode(StrEnum):
    # Account integrity (ADR 0010: never executed « at best »)
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"  # the command targets another account than the one really attached
    ACCOUNT_NOT_CONNECTED = "ACCOUNT_NOT_CONNECTED"
    NOT_ACTIVE_ACCOUNT = "NOT_ACTIVE_ACCOUNT"  # an automatic command may only target the active account
    TRADING_DISABLED = "TRADING_DISABLED"  # the user's « Disable Trading » switch
    # Mode and plumbing
    MODE_NOT_PERMITTING = "MODE_NOT_PERMITTING"  # the autonomy state / ceiling does not allow this route
    HALTED = "HALTED"
    KILL_SWITCH = "KILL_SWITCH"
    AGENT_UNREACHABLE = "AGENT_UNREACHABLE"
    AGENT_CAPABILITY_MISSING = "AGENT_CAPABILITY_MISSING"  # e.g. MODIFY/CLOSE before the agent can handle them
    DEAD_MAN = "DEAD_MAN"  # liveness in doubt, so no new orders: refused by the agent when the core's ping falls silent (EA 1.11)
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"  # the command could not be persisted *before* sending: nothing was sent
    # Risk Engine (ADR 0007: the single control point)
    RISK_NOT_APPROVED = "RISK_NOT_APPROVED"
    RISK_DECISION_EXPIRED = "RISK_DECISION_EXPIRED"
    RISK_DECISION_MISMATCH = "RISK_DECISION_MISMATCH"  # the command deviates from what was approved
    # Request shape
    INVALID_REQUEST = "INVALID_REQUEST"
    STOP_REQUIRED = "STOP_REQUIRED"  # no trade without a stop
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    ORDER_TYPE_UNSUPPORTED = "ORDER_TYPE_UNSUPPORTED"
    COMMAND_EXPIRED = "COMMAND_EXPIRED"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"  # same commandId, different content


class Rejection(DomainModel):
    code: RejectCode
    detail: str
