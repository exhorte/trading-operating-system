"""``Mt5Client`` — the one door to a terminal for reading: account, symbols, quotes, bars, positions, orders, deals.

Everything crossing this boundary becomes a domain model with **true UTC** timestamps (the broker's clock is converted once,
here, through the measured server offset) and no personal data (the holder's name is dropped inside the worker). There is no
method that places, modifies or closes anything: the worker would refuse it anyway.

Connection (ADR 0013): a password is optional. With one, the terminal is initialised with the credentials; without, the
core attaches to the terminal as it is, and — if it is on another login — asks MT5 to switch to an account it already knows.
Either way the attached account is **verified** against the expected login and server before the connection counts.
The password lives in memory for the duration of the call only: it is registered with the log masker and forgotten right after.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr

from trading_os.domain.accounts.models import AccountSnapshot
from trading_os.domain.market.models import Candle, SymbolSpec, Tick
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import Side, Timeframe
from trading_os.infrastructure.mt5.observer_logic import (
    Deal,
    measure_server_offset_minutes,
    server_time_to_utc,
    utc_to_server_epoch,
)
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.infrastructure.mt5.transport import Mt5Transport
from trading_os.shared.errors import AccountMismatch, TradingOsError, Unavailable
from trading_os.shared.logging.redaction import register_secret, unregister_secret
from trading_os.shared.time import Clock, SystemClock

logger = logging.getLogger(__name__)

TRADE_MODES = {0: "demo", 1: "contest", 2: "real"}
MARGIN_MODES = {0: "netting", 1: "exchange", 2: "hedging"}
SYMBOL_TRADE_MODE_FULL = 4
ORDER_KINDS = {2: "limit", 3: "limit", 4: "stop", 5: "stop", 6: "stop_limit", 7: "stop_limit"}
ORDER_SIDES = {
    2: Side.BUY,
    3: Side.SELL,
    4: Side.BUY,
    5: Side.SELL,
    6: Side.BUY,
    7: Side.SELL,
    0: Side.BUY,
    1: Side.SELL,
}

# Fresh enough to measure the broker's clock against ours (see observer_logic.measure_server_offset_minutes).
FRESH_TICK_SECONDS = 15 * 3600


class ConnectFailed(TradingOsError):
    """The terminal could not be attached or logged in. Never carries a secret."""

    code = "login_failed"
    http_status = 502


class _Raw(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Mt5AccountInfo(_Raw):
    login: int
    server: str
    company: str = ""
    currency: str = "USD"
    balance: float
    equity: float
    margin: float = 0.0
    margin_free: float = 0.0
    margin_level: float = 0.0
    leverage: int = 0
    trade_mode: int = 0
    margin_mode: int = 0
    fifo_close: bool = False
    trade_allowed: bool = True
    trade_expert: bool = True


class Mt5TerminalInfo(_Raw):
    connected: bool = False
    trade_allowed: bool = False
    build: int = 0
    path: str = ""


class Mt5Client:
    def __init__(self, transport: Mt5Transport, *, account_id: str, clock: Clock | None = None) -> None:
        self._transport = transport
        self.account_id = account_id
        self._clock = clock or SystemClock()
        self.connected = False
        self.expected_login: int | None = None
        self.server_offset_minutes: int | None = None  # None = never measured
        self.offset_measured_at: datetime | None = None

    # --- connection ---------------------------------------------------------------------------------------------------

    async def connect(
        self,
        *,
        login: int,
        server: str,
        terminal_path: str | None = None,
        password: SecretStr | None = None,
        timeout_s: int = 60,
    ) -> Mt5AccountInfo:
        secret = password.get_secret_value() if password else None
        register_secret(secret)  # masked while it exists anywhere; forgotten in `finally`
        try:
            kwargs: dict[str, Any] = {"timeout": timeout_s * 1000}
            if terminal_path:
                kwargs["path"] = terminal_path
            if secret:
                kwargs.update(login=login, password=secret, server=server)
            try:
                started = await self._transport.call("initialize", **kwargs)
            except WorkerError as error:
                raise ConnectFailed(
                    f"the MT5 terminal could not be started: {error}", code="terminal_unavailable"
                ) from None
            if not started:
                raise ConnectFailed(
                    f"initialize failed ({await self._last_error()}): "
                    + ("check login, password and server" if secret else "is the terminal installed and logged in?"),
                    code="login_failed" if secret else "terminal_unavailable",
                )
            info = await self._account_info_or_none()
            if (info is None or info.login != login) and not secret:
                switched = await self._transport.call("login", login, server=server)
                if not switched:
                    raise ConnectFailed(
                        f"the terminal is not on account {login} and cannot switch to it without a password "
                        f"({await self._last_error()})",
                        code="login_failed",
                    )
                info = await self._account_info_or_none()
            await self._verify(info, login, server)
        except TradingOsError:
            await self._safe_shutdown()
            raise
        finally:
            unregister_secret(secret)
            secret = None
        assert info is not None
        self.connected = True
        self.expected_login = login
        logger.info(
            "MT5 attached to account %s (%s)",
            self.account_id,
            "demo" if info.trade_mode == 0 else TRADE_MODES.get(info.trade_mode, "?"),
        )
        return info

    async def _verify(self, info: Mt5AccountInfo | None, login: int, server: str) -> None:
        if info is None:
            raise ConnectFailed("the terminal is not logged into any account", code="login_failed")
        if info.login != login:
            raise AccountMismatch(
                f"the terminal is attached to another account than {self.account_id}", code="account_mismatch"
            )
        if info.server.strip().lower() != server.strip().lower():
            raise AccountMismatch(
                f"account {self.account_id} is attached on server {info.server!r}, expected {server!r}",
                code="server_mismatch",
            )

    async def disconnect(self) -> None:
        self.connected = False
        await self._safe_shutdown()
        await self._transport.close()

    async def _safe_shutdown(self) -> None:
        with contextlib.suppress(WorkerError, Unavailable):
            await self._transport.call("shutdown", timeout=5)

    async def _last_error(self) -> str:
        try:
            code, message = await self._transport.call("last_error")
            return f"{code}: {message}"
        except (WorkerError, Unavailable, ValueError, TypeError):
            return "no detail"

    # --- account and terminal ----------------------------------------------------------------------------------------------

    async def _account_info_or_none(self) -> Mt5AccountInfo | None:
        raw = await self._transport.call("account_info")
        return Mt5AccountInfo.model_validate(raw) if raw else None

    async def account_info(self) -> Mt5AccountInfo:
        info = await self._account_info_or_none()
        if info is None:
            raise Unavailable("MT5 returned no account information", code="mt5_no_account")
        return info

    async def terminal_info(self) -> Mt5TerminalInfo:
        raw = await self._transport.call("terminal_info")
        return Mt5TerminalInfo.model_validate(raw or {})

    async def is_healthy(self) -> bool:
        """The terminal answers, is connected to its trade server, and is still on the account we expect."""
        try:
            terminal = await self.terminal_info()
            info = await self._account_info_or_none()
        except (WorkerError, Unavailable):
            return False
        return bool(self.connected and terminal.connected and info is not None and info.login == self.expected_login)

    def snapshot_of(self, info: Mt5AccountInfo, *, label: str) -> AccountSnapshot:
        return AccountSnapshot(
            account_id=self.account_id,
            label=label,
            broker=info.company or "MT5",
            currency=info.currency,
            balance=info.balance,
            equity=info.equity,
            daily_pnl=round(info.equity - info.balance, 2),
            margin=info.margin,
            free_margin=info.margin_free,
            margin_level=info.margin_level if info.margin > 0 else None,  # MT5 reports 0 when no margin is used
            server=info.server,
            trade_mode=TRADE_MODES.get(info.trade_mode, "unknown"),
            leverage=info.leverage,
            margin_mode=MARGIN_MODES.get(info.margin_mode, "unknown"),
            fifo_close=info.fifo_close,
            trade_allowed=info.trade_allowed,
            trade_expert=info.trade_expert,
            observed_at=self._clock.now(),
        )

    # --- time ----------------------------------------------------------------------------------------------------------------

    @property
    def offset(self) -> int:
        """The broker clock's offset from UTC in minutes; 0 until it has been measured (and then flagged unknown)."""
        return self.server_offset_minutes or 0

    @property
    def offset_known(self) -> bool:
        return self.server_offset_minutes is not None

    async def measure_server_offset(self, symbol: str) -> int | None:
        """Measure the offset from a fresh tick of ``symbol``. Keeps the previous value (a broker offset only changes with
        DST) when the tick is stale — on a weekend the last tick is days old and says nothing about the clock."""
        raw = await self._transport.call("symbol_info_tick", symbol)
        if not raw:
            return self.server_offset_minutes
        measured = measure_server_offset_minutes(float(raw["time"]), self._clock.now().timestamp())
        if measured is not None:
            self.server_offset_minutes = measured
            self.offset_measured_at = self._clock.now()
        return self.server_offset_minutes

    def use_known_offset(self, minutes: int | None) -> None:
        """Seed the offset from what was measured earlier on this broker server (persisted by the account service)."""
        if self.server_offset_minutes is None:
            self.server_offset_minutes = minutes

    def to_utc(self, server_epoch_seconds: float) -> datetime:
        return server_time_to_utc(server_epoch_seconds, self.offset)

    # --- symbols and quotes --------------------------------------------------------------------------------------------------

    async def select_symbol(self, name: str) -> bool:
        return bool(await self._transport.call("symbol_select", name, True))

    async def symbol_names(self) -> list[str]:
        raw = await self._transport.call("symbols_get")
        return [row["name"] for row in raw or [] if "name" in row]

    async def symbol_spec(self, name: str) -> SymbolSpec | None:
        raw = await self._transport.call("symbol_info", name)
        if not raw:
            return None
        tick_size = float(raw.get("trade_tick_size") or raw.get("point") or 0)
        loss = raw.get("trade_tick_value_loss")
        return SymbolSpec(
            name=name,
            description=raw.get("description", ""),
            currency_base=raw.get("currency_base", ""),
            currency_profit=raw.get("currency_profit", ""),
            currency_margin=raw.get("currency_margin", ""),
            digits=int(raw.get("digits", 0)),
            point=float(raw.get("point") or 10 ** -int(raw.get("digits", 0))),
            tick_size=tick_size,
            tick_value=float(raw.get("trade_tick_value_profit") or raw.get("trade_tick_value") or 0),
            tick_value_loss=float(loss) if loss else None,
            contract_size=float(raw.get("trade_contract_size", 0)),
            volume_min=float(raw.get("volume_min", 0)),
            volume_max=float(raw.get("volume_max", 0)),
            volume_step=float(raw.get("volume_step", 0)),
            stops_level_points=int(raw.get("trade_stops_level", 0)),
            freeze_level_points=int(raw.get("trade_freeze_level", 0)),
            trade_allowed=int(raw.get("trade_mode", 0)) == SYMBOL_TRADE_MODE_FULL,
        )

    async def tick(self, symbol: str) -> Tick | None:
        raw = await self._transport.call("symbol_info_tick", symbol)
        if not raw:
            return None
        return Tick(
            symbol=symbol,
            bid=float(raw["bid"]),
            ask=float(raw["ask"]),
            last=float(raw["last"]) or None,
            time=self.to_utc(raw["time"]),
        )

    # --- bars ---------------------------------------------------------------------------------------------------------------------

    async def candles(self, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        """The last ``count`` bars; only the newest may still be forming."""
        raw = await self._transport.call("copy_rates_from_pos", symbol, {"$tf": timeframe.value}, 0, count)
        return self._candles(symbol, timeframe, raw or [], last_is_forming=True)

    async def candles_between(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> list[Candle]:
        raw = await self._transport.call(
            "copy_rates_range",
            symbol,
            {"$tf": timeframe.value},
            utc_to_server_epoch(start, self.offset),
            utc_to_server_epoch(end, self.offset),
        )
        return self._candles(symbol, timeframe, raw or [], last_is_forming=False)

    def _candles(
        self, symbol: str, timeframe: Timeframe, rows: list[dict[str, Any]], *, last_is_forming: bool
    ) -> list[Candle]:
        candles = []
        for index, row in enumerate(rows):
            forming = last_is_forming and index == len(rows) - 1
            candles.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=self.to_utc(row["time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("tick_volume", 0)),
                    closed=not forming,
                )
            )
        return candles

    # --- positions, orders, deals -----------------------------------------------------------------------------------------------

    async def positions(self, symbol: str | None = None) -> list[Position]:
        raw = await (
            self._transport.call("positions_get", symbol=symbol) if symbol else self._transport.call("positions_get")
        )
        return [self._position(row) for row in raw or []]

    def _position(self, row: dict[str, Any]) -> Position:
        side = Side.BUY if int(row["type"]) == 0 else Side.SELL
        entry, current, stop = (
            float(row["price_open"]),
            float(row.get("price_current") or row["price_open"]),
            float(row.get("sl", 0)),
        )
        risk = abs(entry - stop)
        move = (current - entry) * side.direction
        return Position(
            # POSITION_IDENTIFIER: stable for the life of the position. The ticket is NOT (see observer_logic).
            position_id=str(row["identifier"]),
            account_id=self.account_id,
            symbol=row["symbol"],
            side=side,
            volume=float(row["volume"]),
            entry_price=entry,
            current_price=current,
            stop_loss=stop,
            take_profit=float(row.get("tp", 0)),
            unrealized_pnl=float(row.get("profit", 0)),
            r_multiple=round(move / risk, 2) if risk > 0 and stop > 0 else 0.0,
            magic_number=int(row.get("magic", 0)),
            comment=row.get("comment", ""),
            opened_at=self.to_utc(row["time"]),
        )

    async def orders(self) -> list[PendingOrder]:
        raw = await self._transport.call("orders_get")
        return [
            PendingOrder(
                order_id=str(row["ticket"]),
                account_id=self.account_id,
                symbol=row["symbol"],
                side=ORDER_SIDES.get(int(row["type"]), Side.BUY),
                order_type=ORDER_KINDS.get(int(row["type"]), "other"),
                volume=float(row.get("volume_current", 0)),
                price=float(row.get("price_open", 0)),
                stop_loss=float(row.get("sl", 0)),
                take_profit=float(row.get("tp", 0)),
                magic_number=int(row.get("magic", 0)),
                comment=row.get("comment", ""),
                placed_at=self.to_utc(row["time_setup"]) if row.get("time_setup") else None,
            )
            for row in raw or []
        ]

    async def deals_of_position(self, position_id: str | int) -> list[Deal]:
        raw = await self._transport.call("history_deals_get", position=int(position_id))
        return [Deal.model_validate(row) for row in raw or []]

    async def deals_between(self, start: datetime, end: datetime) -> list[Deal]:
        raw = await self._transport.call(
            "history_deals_get", utc_to_server_epoch(start, self.offset), utc_to_server_epoch(end, self.offset)
        )
        return [Deal.model_validate(row) for row in raw or []]

    async def margin_for(self, side: Side, symbol: str, volume: float, price: float) -> float | None:
        """Read-only: what MT5 says the margin of a hypothetical order would be."""
        result = await self._transport.call("order_calc_margin", 0 if side is Side.BUY else 1, symbol, volume, price)
        return float(result) if result is not None else None
