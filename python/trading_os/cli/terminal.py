"""A read-only attachment to the MetaTrader 5 terminal that is already running and logged in — for the one-shot tools (export history,
list symbols, spread history).

It goes through the same worker as the core: a child process that answers a whitelist of **read** functions and nothing else (no order
function exists in it, a test fails if one ever appears). It never logs in, never asks for a password, and never prints the account's
login or the holder's name (the worker strips the name; the login stays out of every output here).
"""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Any

from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.mt5.client import ConnectFailed, Mt5Client
from trading_os.infrastructure.mt5.transport import Mt5Transport, SubprocessTransport
from trading_os.shared.errors import Unavailable
from trading_os.shared.time import Clock

TRADE_MODES = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
COPY_TICKS_INFO = (
    1  # MetaTrader5.COPY_TICKS_INFO: bid/ask changes only (a constant of the package, which only the worker imports)
)
TICK_TIMEOUT_S = 120.0  # a day of ticks is a large answer


class ReadOnlyTerminal:
    def __init__(self, transport: Mt5Transport, *, clock: Clock | None = None) -> None:
        self._transport = transport
        self.client = Mt5Client(transport, account_id="cli", clock=clock)

    @classmethod
    def real(cls) -> ReadOnlyTerminal:
        return cls(SubprocessTransport(backend="real"))

    # ------------------------------------------------------------------------------------------ life cycle
    async def __aenter__(self) -> ReadOnlyTerminal:
        await self.attach()
        return self

    async def __aexit__(
        self, error_type: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        await self.close()

    async def attach(self, path: str | None = None) -> None:
        """Attach to the terminal as it is (already logged in). Nothing is asked of the broker."""
        kwargs: dict[str, Any] = {"timeout": 60_000}
        if path:
            kwargs["path"] = path
        if not await self._transport.call("initialize", **kwargs):
            raise ConnectFailed(
                "the MT5 terminal could not be attached: is it open and logged in?", code="terminal_unavailable"
            )
        if await self._transport.call("account_info") is None:
            await self.close()
            raise ConnectFailed("the terminal is not logged into any account", code="login_failed")
        self.client.connected = True

    async def close(self) -> None:
        await self.client.disconnect()

    # ------------------------------------------------------------------------------------------ what the tools read
    async def account_summary(self) -> dict[str, str]:
        """The account's trade mode, server and currency — never the login or the holder's name."""
        info = await self.client.account_info()
        return {
            "trade_mode": TRADE_MODES.get(info.trade_mode, str(info.trade_mode)),
            "server": info.server,
            "currency": info.currency,
        }

    async def symbol_info(self, name: str) -> dict[str, Any] | None:
        raw = await self._transport.call("symbol_info", name)
        return raw if isinstance(raw, dict) else None

    async def symbols_like(self, prefix: str) -> list[dict[str, Any]]:
        """Every broker symbol whose name starts with ``prefix`` (and the exact name, if the terminal lists it separately)."""
        rows = await self._transport.call("symbols_get", group=f"{prefix}*") or []
        found = [row for row in rows if isinstance(row, dict) and str(row.get("name", "")).startswith(prefix)]
        exact = await self.symbol_info(prefix)
        if exact is not None and exact.get("name") not in {row.get("name") for row in found}:
            found.append(exact)
        return found

    async def select(self, name: str) -> bool:
        return await self.client.select_symbol(name)

    async def measure_offset(self, symbol: str) -> int | None:
        """The broker clock's offset from UTC, measured from a fresh tick (``None`` when the tick is stale: a weekend says nothing)."""
        return await self.client.measure_server_offset(symbol)

    async def candles_between(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list[Candle]:
        return await self.client.candles_between(symbol, timeframe, start, end)

    async def candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        return await self.client.candles(symbol, timeframe, count)

    async def ticks_between(self, symbol: str, start_server_epoch: int, end_server_epoch: int) -> list[dict[str, Any]]:
        """Bid/ask changes in ``[start, end)`` of the *broker's* clock (epoch seconds, as the package expects)."""
        raw = await self._transport.call(
            "copy_ticks_range", symbol, start_server_epoch, end_server_epoch, COPY_TICKS_INFO, timeout=TICK_TIMEOUT_S
        )
        if raw is None:
            raise Unavailable(f"the terminal returned no ticks for {symbol}", code="mt5_no_ticks")
        return [row for row in raw if isinstance(row, dict)]


def open_terminal() -> ReadOnlyTerminal:
    """The terminal the one-shot tools read. A function, not a constant, so a test can hand in the simulated one."""
    return ReadOnlyTerminal.real()
