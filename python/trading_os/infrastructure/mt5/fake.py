"""A faithful in-memory MT5 terminal: the same functions, the same result shapes, the same quirks as the ``MetaTrader5``
package — so that the whole read path is exercised in tests and in the simulated mode (``MT5_ENABLED=false``) without a
terminal. It has no ordering function: like the real worker it can only *read*.

Quirks reproduced on purpose, because the core has to survive them:

* timestamps (ticks, bars, deals, positions) are **epoch seconds in the broker's clock**, offset from UTC by
  ``server_offset_minutes`` — never true UTC;
* ``initialize()`` / ``login()`` return ``False`` and set ``last_error()`` instead of raising;
* an unknown symbol makes ``symbol_info()`` return ``None``;
* nothing is available before ``initialize()``.

``simulate_feed=True`` makes the quotes move on their own (a smooth deterministic wave), for a cockpit with no terminal.
"""

from __future__ import annotations

import math
import time
from collections import namedtuple
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# --- constants (values of the real package) ---------------------------------------------------------------------
TIMEFRAME_M1, TIMEFRAME_M3, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30 = 1, 3, 5, 15, 30
TIMEFRAME_H1, TIMEFRAME_H4, TIMEFRAME_D1, TIMEFRAME_W1 = 16385, 16388, 16408, 32769
_TIMEFRAME_SECONDS = {1: 60, 3: 180, 5: 300, 15: 900, 30: 1800, 16385: 3600, 16388: 14400, 16408: 86400, 32769: 604800}
POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
DEAL_ENTRY_IN, DEAL_ENTRY_OUT = 0, 1
ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1

AccountInfo = namedtuple(
    "AccountInfo",
    "login trade_mode leverage limit_orders margin_so_mode trade_allowed trade_expert margin_mode currency_digits "
    "fifo_close balance credit profit equity margin margin_free margin_level margin_so_call margin_so_so margin_initial "
    "margin_maintenance assets liabilities commission_blocked name server currency company",
)
TerminalInfo = namedtuple(
    "TerminalInfo",
    "community_account community_connection connected dlls_allowed trade_allowed tradeapi_disabled email_enabled "
    "ftp_enabled notifications_enabled mqid build maxbars codepage ping_last community_balance retransmission company "
    "name language path data_path commondata_path",
)
SymbolInfo = namedtuple(
    "SymbolInfo",
    "custom chart_mode select visible session_deals session_buy_orders session_sell_orders volume volumehigh volumelow "
    "time digits spread spread_float ticks_bookdepth trade_calc_mode trade_mode start_time expiration_time trade_stops_level "
    "trade_freeze_level trade_exemode swap_mode swap_rollover3days margin_hedged_use_leg expiration_mode filling_mode "
    "order_mode order_gtc_mode option_mode option_right bid bidhigh bidlow ask askhigh asklow last lasthigh lastlow "
    "volume_real volumehigh_real volumelow_real option_strike point trade_tick_value trade_tick_value_profit "
    "trade_tick_value_loss trade_tick_size trade_contract_size trade_accrued_interest trade_face_value "
    "trade_liquidity_rate volume_min volume_max volume_step volume_limit swap_long swap_short margin_initial "
    "margin_maintenance session_volume session_turnover session_interest session_buy_orders_volume "
    "session_sell_orders_volume session_open session_close session_aw session_price_settlement session_price_limit_min "
    "session_price_limit_max margin_hedged price_change price_volatility price_theoretical price_greeks_delta "
    "price_greeks_theta price_greeks_gamma price_greeks_vega price_greeks_rho price_greeks_omega price_sensitivity "
    "basis category currency_base currency_profit currency_margin bank external_id exchange description path name",
)
Tick = namedtuple("Tick", "time bid ask last volume time_msc flags volume_real")
TradePosition = namedtuple(
    "TradePosition",
    "ticket time time_msc time_update time_update_msc type magic identifier reason volume price_open sl tp price_current "
    "swap profit symbol comment external_id",
)
TradeOrder = namedtuple(
    "TradeOrder",
    "ticket time_setup time_setup_msc time_expiration type type_time type_filling state magic position_id "
    "position_by_id reason volume_initial volume_current price_open sl tp price_current price_stoplimit symbol comment "
    "external_id",
)
TradeDeal = namedtuple(
    "TradeDeal",
    "ticket order time time_msc type entry magic position_id reason volume price commission swap profit fee symbol "
    "comment external_id",
)


@dataclass
class FakeSymbol:
    name: str
    base_price: float
    spread: float  # price units
    digits: int
    tick_size: float
    tick_value: float  # account currency per tick per lot
    contract_size: float
    currency_base: str
    currency_profit: str
    description: str = ""
    volume_min: float = 0.01
    volume_max: float = 200.0
    volume_step: float = 0.01
    stops_level: int = 0
    freeze_level: int = 0
    trade_mode: int = 4  # SYMBOL_TRADE_MODE_FULL
    amplitude: float = 0.0  # simulated feed only
    bid: float | None = None
    ask: float | None = None
    tick_time: int | None = None  # fixed tick timestamp (server clock); None = "now"
    visible: bool = True

    @property
    def point(self) -> float:
        return float(10**-self.digits)


@dataclass
class FakeAccount:
    login: int
    server: str
    password: str
    company: str = "Simulated Broker"
    currency: str = "USD"
    balance: float = 10_000.0
    leverage: int = 500
    trade_mode: int = 0  # ACCOUNT_TRADE_MODE_DEMO
    margin_mode: int = 2  # RETAIL_HEDGING
    trade_allowed: bool = True


@dataclass
class FakeMt5:
    accounts: dict[int, FakeAccount] = field(default_factory=dict)
    symbols: dict[str, FakeSymbol] = field(default_factory=dict)
    server_offset_minutes: int = 0
    simulate_feed: bool = False
    clock: Callable[[], float] = time.time
    # state
    initialized: bool = False
    current_login: int | None = None
    error: tuple[int, str] = (1, "Success")
    positions: list[TradePosition] = field(default_factory=list)
    deals: list[TradeDeal] = field(default_factory=list)
    orders: list[TradeOrder] = field(default_factory=list)
    terminal_connected: bool = True
    initialize_fails: bool = False

    # constants exposed as attributes, like the module
    TIMEFRAME_M1 = TIMEFRAME_M1
    TIMEFRAME_M3 = TIMEFRAME_M3
    TIMEFRAME_M5 = TIMEFRAME_M5
    TIMEFRAME_M15 = TIMEFRAME_M15
    TIMEFRAME_M30 = TIMEFRAME_M30
    TIMEFRAME_H1 = TIMEFRAME_H1
    TIMEFRAME_H4 = TIMEFRAME_H4
    TIMEFRAME_D1 = TIMEFRAME_D1
    TIMEFRAME_W1 = TIMEFRAME_W1

    @classmethod
    def default(cls) -> FakeMt5:
        """A ready simulated terminal: one demo account, three instruments, a moving feed."""
        return cls(
            accounts={
                1000001: FakeAccount(
                    login=1000001, server="Sim-Server", password="sim-password", company="Simulated Broker"
                )
            },
            symbols={
                "EURUSDm": FakeSymbol(
                    "EURUSDm",
                    1.0850,
                    0.00008,
                    5,
                    0.00001,
                    1.0,
                    100_000,
                    "EUR",
                    "USD",
                    "Euro vs US Dollar",
                    amplitude=0.0030,
                ),
                "GBPUSDm": FakeSymbol(
                    "GBPUSDm",
                    1.2650,
                    0.00010,
                    5,
                    0.00001,
                    1.0,
                    100_000,
                    "GBP",
                    "USD",
                    "Pound vs US Dollar",
                    amplitude=0.0040,
                ),
                "XAUUSDm": FakeSymbol(
                    "XAUUSDm", 3300.0, 0.26, 3, 0.001, 0.1, 100, "XAU", "USD", "Gold vs US Dollar", amplitude=12.0
                ),
            },
            simulate_feed=True,
        )

    # --- internals ----------------------------------------------------------------------------------------------------

    def _now(self) -> float:
        return self.clock()

    def _server_now(self) -> int:
        return int(self._now() + self.server_offset_minutes * 60)

    def _account(self) -> FakeAccount | None:
        return self.accounts.get(self.current_login) if self.current_login is not None else None

    def _ok(self) -> bool:
        if not self.initialized:
            self.error = (-10004, "No IPC connection")
            return False
        return True

    def _price(self, symbol: FakeSymbol, at: float) -> float:
        if symbol.bid is not None and symbol.ask is not None and not self.simulate_feed:
            return (symbol.bid + symbol.ask) / 2
        wave = math.sin(at / 600.0) + 0.4 * math.sin(at / 97.0)
        return symbol.base_price + symbol.amplitude * wave

    # --- connection ------------------------------------------------------------------------------------------------------

    def initialize(
        self,
        path: str | None = None,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        timeout: int | None = None,
        portable: bool = False,
    ) -> bool:
        if self.initialize_fails:
            self.error = (-10003, "IPC initialize failed, MetaTrader 5 x64 not found")
            return False
        self.initialized = True
        if login is None:
            if self.current_login is None and self.accounts:
                self.current_login = next(iter(self.accounts))
            self.error = (1, "Success")
            return True
        return self.login(login, password=password, server=server)

    def login(self, login: int, password: str | None = None, server: str | None = None, timeout: int = 60000) -> bool:
        if not self._ok():
            return False
        account = self.accounts.get(int(login))
        if account is None or (server is not None and server != account.server):
            self.error = (-6, "Terminal: Authorization failed")
            return False
        if password is not None and password != account.password:
            self.error = (-6, "Terminal: Authorization failed")
            return False
        self.current_login = account.login
        self.error = (1, "Success")
        return True

    def shutdown(self) -> None:
        self.initialized = False

    def last_error(self) -> tuple[int, str]:
        return self.error

    def version(self) -> tuple[int, int, str]:
        return (500, 5735, "01 Jan 2026")

    # --- account and terminal --------------------------------------------------------------------------------------------

    def account_info(self) -> Any:
        account = self._account()
        if not self._ok() or account is None:
            return None
        profit = sum(p.profit for p in self.positions)
        margin = 0.0
        equity = account.balance + profit
        return AccountInfo(
            login=account.login,
            trade_mode=account.trade_mode,
            leverage=account.leverage,
            limit_orders=200,
            margin_so_mode=0,
            trade_allowed=account.trade_allowed,
            trade_expert=True,
            margin_mode=account.margin_mode,
            currency_digits=2,
            fifo_close=False,
            balance=account.balance,
            credit=0.0,
            profit=profit,
            equity=equity,
            margin=margin,
            margin_free=equity - margin,
            margin_level=0.0,
            margin_so_call=50.0,
            margin_so_so=30.0,
            margin_initial=0.0,
            margin_maintenance=0.0,
            assets=0.0,
            liabilities=0.0,
            commission_blocked=0.0,
            name="Simulated Holder",
            server=account.server,
            currency=account.currency,
            company=account.company,
        )

    def terminal_info(self) -> Any:
        if not self._ok():
            return None
        return TerminalInfo(
            community_account=False,
            community_connection=False,
            connected=self.terminal_connected,
            dlls_allowed=False,
            trade_allowed=True,
            tradeapi_disabled=False,
            email_enabled=False,
            ftp_enabled=False,
            notifications_enabled=False,
            mqid=False,
            build=5735,
            maxbars=100000,
            codepage=0,
            ping_last=25_000,
            community_balance=0.0,
            retransmission=0.0,
            company="Simulated Broker",
            name="MetaTrader 5 (simulated)",
            language="English",
            path="C:\\Simulated\\MetaTrader 5",
            data_path="C:\\Simulated\\Data",
            commondata_path="C:\\Simulated\\Common",
        )

    # --- symbols and quotes ------------------------------------------------------------------------------------------------

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        info = self.symbols.get(symbol)
        if not self._ok() or info is None:
            return False
        info.visible = enable
        return True

    def symbols_total(self) -> int:
        return len(self.symbols)

    def symbols_get(self, group: str | None = None) -> Any:
        return tuple(self.symbol_info(name) for name in self.symbols) if self._ok() else None

    def symbol_info(self, symbol: str) -> Any:
        s = self.symbols.get(symbol)
        if not self._ok() or s is None:
            return None
        tick = self.symbol_info_tick(symbol)
        bid, ask = (tick.bid, tick.ask) if tick else (0.0, 0.0)
        values: dict[str, Any] = dict.fromkeys(SymbolInfo._fields, 0)
        values.update(
            custom=False,
            select=s.visible,
            visible=s.visible,
            digits=s.digits,
            spread=round(s.spread / s.point),
            spread_float=True,
            trade_mode=s.trade_mode,
            trade_stops_level=s.stops_level,
            trade_freeze_level=s.freeze_level,
            bid=bid,
            ask=ask,
            point=s.point,
            trade_tick_value=s.tick_value,
            trade_tick_value_profit=s.tick_value,
            trade_tick_value_loss=s.tick_value,
            trade_tick_size=s.tick_size,
            trade_contract_size=s.contract_size,
            volume_min=s.volume_min,
            volume_max=s.volume_max,
            volume_step=s.volume_step,
            currency_base=s.currency_base,
            currency_profit=s.currency_profit,
            currency_margin=s.currency_base,
            description=s.description,
            path=f"Forex\\{s.name}",
            time=tick.time if tick else 0,
            name=s.name,
        )
        return SymbolInfo(**values)

    def symbol_info_tick(self, symbol: str) -> Any:
        s = self.symbols.get(symbol)
        if not self._ok() or s is None:
            return None
        if s.bid is not None and s.ask is not None and not self.simulate_feed:
            bid, ask = s.bid, s.ask
        else:
            mid = self._price(s, self._now())
            bid, ask = round(mid - s.spread / 2, s.digits), round(mid + s.spread / 2, s.digits)
        when = s.tick_time if s.tick_time is not None else self._server_now()
        return Tick(time=when, bid=bid, ask=ask, last=0.0, volume=0, time_msc=when * 1000, flags=6, volume_real=0.0)

    # --- positions, orders, history ------------------------------------------------------------------------------------------

    def positions_get(self, symbol: str | None = None, group: str | None = None, ticket: int | None = None) -> Any:
        if not self._ok():
            return None
        rows = [
            p
            for p in self.positions
            if (symbol is None or p.symbol == symbol) and (ticket is None or p.ticket == ticket)
        ]
        return tuple(rows)

    def positions_total(self) -> int:
        return len(self.positions)

    def orders_get(self, symbol: str | None = None, group: str | None = None, ticket: int | None = None) -> Any:
        if not self._ok():
            return None
        return tuple(
            o for o in self.orders if (symbol is None or o.symbol == symbol) and (ticket is None or o.ticket == ticket)
        )

    def orders_total(self) -> int:
        return len(self.orders)

    def history_deals_get(
        self,
        date_from: Any = None,
        date_to: Any = None,
        group: str | None = None,
        ticket: int | None = None,
        position: int | None = None,
    ) -> Any:
        if not self._ok():
            return None
        if position is not None:
            return tuple(d for d in self.deals if d.position_id == position)
        start, end = _as_seconds(date_from), _as_seconds(date_to)
        return tuple(d for d in self.deals if (start is None or d.time >= start) and (end is None or d.time <= end))

    def history_orders_get(self, *args: Any, **kwargs: Any) -> Any:
        return () if self._ok() else None

    # --- bars and ticks --------------------------------------------------------------------------------------------------------

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start_pos: int, count: int) -> Any:
        s = self.symbols.get(symbol)
        seconds = _TIMEFRAME_SECONDS.get(timeframe)
        if not self._ok() or s is None or seconds is None:
            return None
        newest_open = (self._server_now() // seconds) * seconds - start_pos * seconds
        return self._bars(s, seconds, [newest_open - i * seconds for i in range(count - 1, -1, -1)])

    def copy_rates_range(self, symbol: str, timeframe: int, date_from: Any, date_to: Any) -> Any:
        s = self.symbols.get(symbol)
        seconds = _TIMEFRAME_SECONDS.get(timeframe)
        if not self._ok() or s is None or seconds is None:
            return None
        start, end = _as_seconds(date_from) or 0, _as_seconds(date_to) or self._server_now()
        first = ((start + seconds - 1) // seconds) * seconds
        return self._bars(s, seconds, list(range(first, end + 1, seconds))[:5000])

    def copy_rates_from(self, symbol: str, timeframe: int, date_from: Any, count: int) -> Any:
        seconds = _TIMEFRAME_SECONDS.get(timeframe)
        end = _as_seconds(date_from) or self._server_now()
        if seconds is None:
            return None
        newest = (end // seconds) * seconds
        s = self.symbols.get(symbol)
        return (
            None
            if not self._ok() or s is None
            else self._bars(s, seconds, [newest - i * seconds for i in range(count - 1, -1, -1)])
        )

    def copy_ticks_from(self, *args: Any, **kwargs: Any) -> Any:
        return [] if self._ok() else None

    def copy_ticks_range(self, *args: Any, **kwargs: Any) -> Any:
        return [] if self._ok() else None

    def _bars(self, s: FakeSymbol, seconds: int, opens: list[int]) -> list[dict[str, Any]]:
        bars = []
        for open_time in opens:
            real_open = open_time - self.server_offset_minutes * 60
            samples = [self._price(s, real_open + seconds * k / 4) for k in range(5)]
            o, c = samples[0], samples[-1]
            bars.append(
                {
                    "time": open_time,
                    "open": round(o, s.digits),
                    "high": round(max(samples), s.digits),
                    "low": round(min(samples), s.digits),
                    "close": round(c, s.digits),
                    "tick_volume": 100 + (open_time % 50),
                    "spread": round(s.spread / s.point),
                    "real_volume": 0,
                }
            )
        return bars

    # --- read-only calculators ---------------------------------------------------------------------------------------------------

    def order_calc_profit(self, action: int, symbol: str, volume: float, price_open: float, price_close: float) -> Any:
        s = self.symbols.get(symbol)
        if not self._ok() or s is None:
            return None
        direction = 1 if action == ORDER_TYPE_BUY else -1
        return (price_close - price_open) * direction / s.tick_size * s.tick_value * volume

    def order_calc_margin(self, action: int, symbol: str, volume: float, price: float) -> Any:
        s = self.symbols.get(symbol)
        account = self._account()
        if not self._ok() or s is None or account is None:
            return None
        return volume * s.contract_size * price / account.leverage

    # --- test helpers (NOT part of the MT5 API, never reachable through the worker whitelist) ----------------------------------------

    def set_quote(self, symbol: str, bid: float, ask: float, *, server_time: int | None = None) -> None:
        s = self.symbols[symbol]
        s.bid, s.ask, s.tick_time = bid, ask, server_time
        self.simulate_feed = False

    def add_position(
        self,
        *,
        identifier: int,
        symbol: str,
        side: int,
        volume: float,
        price_open: float,
        sl: float = 0.0,
        tp: float = 0.0,
        profit: float = 0.0,
        magic: int = 0,
        comment: str = "",
        ticket: int | None = None,
        opened_server_time: int | None = None,
        price_current: float | None = None,
    ) -> TradePosition:
        opened = opened_server_time if opened_server_time is not None else self._server_now()
        position = TradePosition(
            ticket=ticket if ticket is not None else identifier,
            time=opened,
            time_msc=opened * 1000,
            time_update=opened,
            time_update_msc=opened * 1000,
            type=side,
            magic=magic,
            identifier=identifier,
            reason=0,
            volume=volume,
            price_open=price_open,
            sl=sl,
            tp=tp,
            price_current=price_current if price_current is not None else price_open,
            swap=0.0,
            profit=profit,
            symbol=symbol,
            comment=comment,
            external_id="",
        )
        self.positions.append(position)
        return position

    def remove_position(self, identifier: int) -> None:
        self.positions = [p for p in self.positions if p.identifier != identifier]

    def add_deal(
        self,
        *,
        position_id: int,
        symbol: str,
        side: int,
        entry: int,
        volume: float,
        price: float,
        server_time: int,
        profit: float = 0.0,
        commission: float = 0.0,
        swap: float = 0.0,
        magic: int = 0,
        comment: str = "",
    ) -> TradeDeal:
        deal = TradeDeal(
            ticket=len(self.deals) + 1,
            order=len(self.deals) + 1,
            time=server_time,
            time_msc=server_time * 1000,
            type=side,
            entry=entry,
            magic=magic,
            position_id=position_id,
            reason=0,
            volume=volume,
            price=price,
            commission=commission,
            swap=swap,
            profit=profit,
            fee=0.0,
            symbol=symbol,
            comment=comment,
            external_id="",
        )
        self.deals.append(deal)
        return deal


def _as_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return int(value)
    return int(value.timestamp())
