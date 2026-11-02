"""The execution-agent wire (NDJSON over TCP): lean, versioned JSON, one message per line.

This is the **one** place where the MT5 edge's vocabulary (``BUY``/``SELL``, epoch milliseconds, flat fields) is converted
to the domain's; nothing downstream sees it. It is the only wire the core speaks with MT5 (the read path is a worker process).

Parsing is lenient where the agent was historically sloppy (ids and return codes as numbers or strings) and silent
on garbage: a malformed frame is dropped, never raised (« never crash the core »). The ``token`` of a hello is read
from the raw line by the server and is deliberately not a field of any model: it is never kept, logged or persisted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel

from trading_os.domain.primitives import Side
from trading_os.shared.time import from_epoch_ms

WIRE_VERSION = 1


def _as_text(value: Any) -> Any:
    """Broker ids and return codes are strings on the wire; an older agent sent numbers."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return str(int(value)) if float(value).is_integer() else str(value)
    return value


WireText = Annotated[str | None, BeforeValidator(_as_text)]


class WireMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, alias_generator=to_camel)

    version: int = WIRE_VERSION
    type: str
    account_id: str  # the MT5 login, as a string
    time: int = 0  # epoch milliseconds, UTC

    @property
    def at(self) -> datetime:
        return from_epoch_ms(self.time)


class AgentHello(WireMessage):
    type: Literal["agent.hello"] = "agent.hello"
    agent_id: str
    symbol: str = ""
    broker: str = ""
    server: str = ""
    order_types: list[str] = []
    min_volume: float = 0.0
    max_volume: float = 0.0
    volume_step: float = 0.0
    filling_mode: str = ""
    stops_level_points: int = 0
    mode: str = "observe"
    agent_version: str = ""
    server_utc_offset_minutes: int = 0
    # Execution agent only (I1)
    capabilities: list[str] | None = None
    build_id: str | None = None
    mode_ceiling: str | None = None
    identity: Literal["ok", "mismatch", "no_account"] | None = None
    expected_account_id: str | None = None
    trade_mode: str | None = None
    margin_mode: str | None = None
    fifo_close: bool | None = None
    leverage: int | None = None
    currency: str | None = None
    terminal_trade_allowed: bool | None = None
    expert_trade_allowed: bool | None = None
    account_trade_expert: bool | None = None
    account_trade_allowed: bool | None = None
    tradable: bool | None = None
    closable: bool | None = None
    halted: bool | None = None
    attached_experts: list[str] | None = None


class AgentHeartbeat(WireMessage):
    type: Literal["agent.heartbeat"] = "agent.heartbeat"
    agent_id: str
    latency_ms: float = 0.0
    mode: str | None = None
    identity: Literal["ok", "mismatch", "no_account"] | None = None
    terminal_trade_allowed: bool | None = None
    expert_trade_allowed: bool | None = None
    account_trade_expert: bool | None = None
    account_trade_allowed: bool | None = None
    halted: bool | None = None
    # How long the agent has gone without hearing from the core. ``gatewaySilentMs`` is the name agents built before 1.11 still
    # send (the .NET Gateway they were written for no longer exists): read it until every agent is recompiled, then drop it.
    core_silent_ms: int | None = Field(default=None, validation_alias=AliasChoices("coreSilentMs", "gatewaySilentMs"))
    attached_experts: list[str] | None = None


class AgentError(WireMessage):
    type: Literal["agent.error"] = "agent.error"
    agent_id: str = ""
    code: str = ""
    message: str = ""


class ExecutionAck(WireMessage):
    type: Literal["execution.ack"] = "execution.ack"
    command_id: str
    status: Literal["ACCEPTED", "REJECTED", "DUPLICATE", "EXPIRED"]
    reason: str | None = None


#: Final reports that mean « the broker did what the command asked » (ADR 0029): a market order filled (FILLED, PARTIALLY_FILLED),
#: a pending order resting at the broker (SUBMITTED — nothing is filled yet), a stop moved (MODIFIED), a position closed in whole or
#: in part (CLOSED), a pending order deleted (CANCELLED). Each takes the command to EXECUTED.
SUCCESS_REPORT_STATUSES = frozenset({"FILLED", "PARTIALLY_FILLED", "SUBMITTED", "MODIFIED", "CLOSED", "CANCELLED"})


class ExecutionReport(WireMessage):
    type: Literal["execution.report"] = "execution.report"
    command_id: str
    status: Literal[
        "SIMULATED", "SUBMITTED", "FILLED", "PARTIALLY_FILLED", "MODIFIED", "CLOSED", "CANCELLED", "FAILED", "REJECTED"
    ]
    symbol: str = ""
    side: Literal["BUY", "SELL"] | None = None
    broker_order_id: WireText = None
    broker_position_id: WireText = None
    filled_volume: float | None = None
    average_price: float | None = None
    broker_retcode: WireText = None
    detail: str = ""
    replayed: bool = False  # a final report sent again after a reconnection, with its original time


class ExecutionReconciled(WireMessage):
    type: Literal["execution.reconciled"] = "execution.reconciled"
    command_id: str
    outcome: Literal["executed", "rejected", "not_found"]
    symbol: str | None = None
    side: Literal["BUY", "SELL"] | None = None
    broker_order_id: WireText = None
    broker_position_id: WireText = None
    filled_volume: float | None = None
    average_price: float | None = None
    broker_retcode: WireText = None
    attempts: int = 0
    detail: str = ""


class PositionScan(WireMessage):
    type: Literal["execution.position.scan"] = "execution.position.scan"
    broker_position_id: WireText
    symbol: str
    side: Literal["BUY", "SELL"]
    volume: float
    magic_number: int = 0
    is_external: bool = False
    known_command_id: str | None = None


AgentMessage = (
    AgentHello | AgentHeartbeat | AgentError | ExecutionAck | ExecutionReport | ExecutionReconciled | PositionScan
)

_MODELS: dict[str, type[WireMessage]] = {
    "agent.hello": AgentHello,
    "agent.heartbeat": AgentHeartbeat,
    "agent.error": AgentError,
    "execution.ack": ExecutionAck,
    "execution.report": ExecutionReport,
    "execution.reconciled": ExecutionReconciled,
    "execution.position.scan": PositionScan,
}


@dataclass(frozen=True)
class AgentFrame:
    """One decoded line. ``message`` is None for anything unreadable or of a type the core does not consume."""

    message: AgentMessage | None
    message_type: str | None
    token: str | None  # only ever set for a hello; read here so no model carries it


def decode_line(line: str) -> AgentFrame:
    try:
        raw = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return AgentFrame(None, None, None)
    if not isinstance(raw, dict):
        return AgentFrame(None, None, None)
    message_type = raw.get("type") if isinstance(raw.get("type"), str) else None
    model = _MODELS.get(message_type or "")
    if model is None:
        return AgentFrame(None, message_type, None)
    token = raw.get("token") if message_type == "agent.hello" and isinstance(raw.get("token"), str) else None
    try:
        message = model.model_validate(raw)
    except ValueError:  # pydantic.ValidationError is a ValueError
        return AgentFrame(None, message_type, token)
    return AgentFrame(message, message_type, token)  # type: ignore[arg-type]


# --- outbound ---------------------------------------------------------------------------------------------------


def _line(payload: dict[str, Any]) -> bytes:
    """UTF-8 **without** a byte-order mark (a BOM before the first command was a real bug once), newline-terminated."""
    return (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def side_to_wire(side: Side) -> str:
    return "BUY" if side is Side.BUY else "SELL"


def side_from_wire(side: str) -> Side:
    return Side.BUY if side == "BUY" else Side.SELL


def order_line(
    *,
    login: str,
    command_id: str,
    expires_at_ms: int,
    now_ms: int,
    symbol: str,
    side: Side,
    volume: float,
    stop_loss: float,
    take_profit: float,
    order_type: str = "MARKET",
    limit_price: float | None = None,
) -> bytes:
    return _line(
        {
            "version": WIRE_VERSION,
            "type": "execution.order",
            "accountId": login,
            "time": now_ms,
            "id": command_id,
            "expiresAt": expires_at_ms,
            "symbol": symbol,
            "side": side_to_wire(side),
            "orderType": order_type,
            "volume": volume,
            "limitPrice": limit_price,
            "sl": stop_loss,
            "tp": take_profit,
        }
    )


def modify_line(
    *,
    login: str,
    command_id: str,
    expires_at_ms: int,
    now_ms: int,
    symbol: str,
    position_id: str,
    stop_loss: float | None,
    take_profit: float | None,
) -> bytes:
    """Move the stop and/or the target of an open position. ``None`` leaves that level as it is. The core has already refused any
    stop that would be looser than the current one (ADR 0023); the agent checks again and has the last word."""
    return _line(
        {
            "version": WIRE_VERSION,
            "type": "execution.modify",
            "accountId": login,
            "time": now_ms,
            "id": command_id,
            "expiresAt": expires_at_ms,
            "symbol": symbol,
            "positionId": position_id,
            "sl": stop_loss,
            "tp": take_profit,
        }
    )


def close_line(
    *,
    login: str,
    command_id: str,
    expires_at_ms: int,
    now_ms: int,
    symbol: str,
    position_id: str,
    volume: float | None = None,
) -> bytes:
    """Close a position — all of it, or ``volume`` lots of it (PARTIAL_CLOSE)."""
    return _line(
        {
            "version": WIRE_VERSION,
            "type": "execution.close",
            "accountId": login,
            "time": now_ms,
            "id": command_id,
            "expiresAt": expires_at_ms,
            "symbol": symbol,
            "positionId": position_id,
            "volume": volume,
        }
    )


def cancel_line(*, login: str, command_id: str, expires_at_ms: int, now_ms: int, symbol: str, order_id: str) -> bytes:
    """Delete a pending order that has not filled."""
    return _line(
        {
            "version": WIRE_VERSION,
            "type": "execution.cancel",
            "accountId": login,
            "time": now_ms,
            "id": command_id,
            "expiresAt": expires_at_ms,
            "symbol": symbol,
            "orderId": order_id,
        }
    )


def ping_line(now_ms: int) -> bytes:
    return _line({"version": WIRE_VERSION, "type": "control.ping", "time": now_ms})


def halt_line(reason: str, now_ms: int) -> bytes:
    return _line({"version": WIRE_VERSION, "type": "control.halt", "time": now_ms, "reason": reason})
