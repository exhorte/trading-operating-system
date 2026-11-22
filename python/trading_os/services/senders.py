"""Order senders: where an approved, persisted command goes. One way out is real, so one sender exists (ADR 0041: no simulated outcome any more):

* ``AgentSender`` — CONFIRM / ARMED / AUTONOMOUS: the one and only way an order leaves the core, over the local socket
  to the MetaTrader 5 execution agent, which holds the single ``OrderSend`` (and refuses anything its own barriers refuse).

OFF, OBSERVE and HALTED have no sender: an order asked for in those modes is **refused with a code** (``MODE_NOT_PERMITTING``) and recorded as
refused, never as if it had been done. The core never calls an order function of the ``MetaTrader5`` package: there is none in its read-only
worker. Making « OBSERVE sends nothing » a *test* rather than a promise is the reason for this seam.
"""

from __future__ import annotations

from typing import Literal, Protocol

from trading_os.domain.accounts.models import Account
from trading_os.domain.execution.commands import CommandKind, ExecutionCommand
from trading_os.domain.primitives import DomainModel
from trading_os.infrastructure.mt5.wire import cancel_line, close_line, modify_line, order_line
from trading_os.shared.time import Clock, to_epoch_ms


class SendResult(DomainModel):
    kind: Literal["sent", "not_sent"]
    detail: str = ""
    average_price: float | None = None
    filled_volume: float | None = None


class OrderSender(Protocol):
    name: str

    async def send(self, command: ExecutionCommand, account: Account) -> SendResult: ...


class AgentLink(Protocol):
    """The part of the execution-agent socket a sender needs."""

    async def send_line(self, login: str, line: bytes) -> bool: ...


class AgentSender:
    name = "ea"

    def __init__(self, link: AgentLink, clock: Clock) -> None:
        self._link = link
        self._clock = clock

    async def send(self, command: ExecutionCommand, account: Account) -> SendResult:
        request = command.request
        login = str(account.login)
        expires_at_ms = to_epoch_ms(command.expires_at)
        now_ms = to_epoch_ms(self._clock.now())
        if request.kind is not CommandKind.OPEN:
            line = self._management_line(command, login, expires_at_ms, now_ms)
            if line is None:
                return SendResult(kind="not_sent", detail=f"incomplete {request.kind.value}: its target is missing")
            return await self._deliver(login, line)
        if request.side is None or request.volume is None or request.stop_loss is None:
            return SendResult(kind="not_sent", detail="incomplete order: side, volume and stop loss are required")
        line = order_line(
            login=str(account.login),
            command_id=request.command_id,
            expires_at_ms=to_epoch_ms(command.expires_at),
            now_ms=to_epoch_ms(self._clock.now()),
            symbol=request.symbol,
            side=request.side,
            volume=request.volume,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit or 0.0,
            order_type=request.order_type.value.upper(),
            limit_price=request.price,
        )
        return await self._deliver(str(account.login), line)

    @staticmethod
    def _management_line(command: ExecutionCommand, login: str, expires_at_ms: int, now_ms: int) -> bytes | None:
        request = command.request
        if request.kind is CommandKind.CANCEL:
            if not request.order_id:
                return None
            return cancel_line(
                login=login, command_id=request.command_id, expires_at_ms=expires_at_ms, now_ms=now_ms,
                symbol=request.symbol, order_id=request.order_id,
            )  # fmt: skip
        if not request.position_id:
            return None
        if request.kind is CommandKind.MODIFY:
            return modify_line(
                login=login, command_id=request.command_id, expires_at_ms=expires_at_ms, now_ms=now_ms,
                symbol=request.symbol, position_id=request.position_id, stop_loss=request.stop_loss,
                take_profit=request.take_profit,
            )  # fmt: skip
        return close_line(
            login=login, command_id=request.command_id, expires_at_ms=expires_at_ms, now_ms=now_ms,
            symbol=request.symbol, position_id=request.position_id,
            volume=request.volume if request.kind is CommandKind.PARTIAL_CLOSE else None,
        )  # fmt: skip

    async def _deliver(self, login: str, line: bytes) -> SendResult:
        if await self._link.send_line(login, line):
            return SendResult(kind="sent", detail="handed to the execution agent")
        return SendResult(kind="not_sent", detail="the execution agent could not be reached: nothing was sent")
