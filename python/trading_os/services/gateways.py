"""Order gateways: where an approved, persisted command goes. Three of them exist because three execution routes are real:

* ``ObserveGateway`` — OBSERVE / OFF: the command is validated and recorded, and **nothing is sent anywhere**;
* ``PaperGateway`` — PAPER: a simulated fill at the live quote, in this process, never MT5;
* ``EaLinkGateway`` — CONFIRM / ARMED / AUTONOMOUS: the one and only way an order leaves the core, over the local socket
  to the MetaTrader 5 execution agent, which holds the single ``OrderSend`` (and refuses anything its own barriers refuse).

The core never calls an order function of the ``MetaTrader5`` package: there is none in its read-only worker. Making
« OBSERVE sends nothing » a *test* rather than a promise is the reason for this seam.
"""

from __future__ import annotations

from typing import Literal, Protocol

from trading_os.domain.accounts.models import Account
from trading_os.domain.execution.commands import ExecutionCommand
from trading_os.domain.primitives import DomainModel, Side
from trading_os.infrastructure.mt5.wire import order_line
from trading_os.services.market_data import MarketDataService
from trading_os.shared.time import Clock, to_epoch_ms


class SendResult(DomainModel):
    kind: Literal["sent", "not_sent", "simulated"]
    detail: str = ""
    average_price: float | None = None
    filled_volume: float | None = None


class OrderGateway(Protocol):
    name: str

    async def send(self, command: ExecutionCommand, account: Account) -> SendResult: ...


class AgentLink(Protocol):
    """The part of the execution-agent socket a gateway needs."""

    async def send_line(self, login: str, line: bytes) -> bool: ...


class ObserveGateway:
    name = "observe"

    async def send(self, command: ExecutionCommand, account: Account) -> SendResult:
        return SendResult(kind="simulated", detail="OBSERVE: validated and recorded — nothing was sent anywhere")


class PaperGateway:
    name = "paper"

    def __init__(self, market: MarketDataService) -> None:
        self._market = market

    async def send(self, command: ExecutionCommand, account: Account) -> SendResult:
        request = command.request
        tick = self._market.tick(account.id, request.symbol)
        if tick is None or request.side is None or request.volume is None:
            return SendResult(kind="not_sent", detail="paper broker has no quote for the symbol: no simulated fill")
        price = tick.ask if request.side is Side.BUY else tick.bid
        return SendResult(
            kind="simulated",
            detail=f"PAPER: simulated fill at {price:g} (no broker order exists)",
            average_price=price,
            filled_volume=request.volume,
        )


class EaLinkGateway:
    name = "ea"

    def __init__(self, link: AgentLink, clock: Clock) -> None:
        self._link = link
        self._clock = clock

    async def send(self, command: ExecutionCommand, account: Account) -> SendResult:
        request = command.request
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
        if await self._link.send_line(str(account.login), line):
            return SendResult(kind="sent", detail="handed to the execution agent")
        return SendResult(kind="not_sent", detail="the execution agent could not be reached: nothing was sent")
