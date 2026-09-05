"""
MT5 observe-only agent (Phase 05 producer + Phase 09 SIMULATED execution).

Reads REAL data from a locally running, already-logged-in MetaTrader 5 terminal
(account, positions, ticks, M15 candles) and streams it as lean JSON over a
local WebSocket (lib/contracts/mt5-wire.ts). Since Phase 09 it also RECEIVES
execution.order commands from the gateway and answers with execution.ack and a
SIMULATED execution.report — validating the full command loop at zero risk.

SAFETY — this script can never trade:
  * EXECUTION_MODE is the constant "observe"; any other mode is refused;
  * it NEVER imports or calls any order/trade function
    (no order_send, no positions modify/close). Grep this file: there are none.
    A "fill" here is a JSON reply, nothing else.
  * rejected / expired / duplicate commands NEVER produce a report;
  * it needs NO credentials — the terminal is already authenticated locally.

Usage (Windows, terminal open and logged into your Exness demo):
    pip install -r requirements.txt
    python mt5_observer.py --symbol XAUUSDm

Then run the backend gateway + the cockpit with NEXT_PUBLIC_REALTIME_SOURCE=backend
(runbook: context/backend/backend_bootstrap.md).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

import MetaTrader5 as mt5
import websockets

WIRE_VERSION = 1
AGENT_ID = "mt5-observer-1"
AGENT_VERSION = "0.2.0-observer"
TIMEFRAME_LABEL = "M15"

# Constant by design: this agent has no other mode and no trading code path.
EXECUTION_MODE = "observe"

# Idempotency: command ids already processed (survives client reconnects).
_seen_command_ids: set[str] = set()


def now_ms() -> int:
    return int(time.time() * 1000)


def account_id() -> str:
    info = mt5.account_info()
    return str(info.login) if info else "unknown"


def build_hello(symbol: str) -> dict[str, Any]:
    info = mt5.account_info()
    sym = mt5.symbol_info(symbol)
    return {
        "version": WIRE_VERSION,
        "type": "agent.hello",
        "accountId": account_id(),
        "time": now_ms(),
        "agentId": AGENT_ID,
        "symbol": symbol,
        "broker": info.company if info else "unknown",
        "server": info.server if info else "unknown",
        "orderTypes": ["market"],  # observe mode never places any of these
        "minVolume": sym.volume_min if sym else 0.0,
        "maxVolume": sym.volume_max if sym else 0.0,
        "volumeStep": sym.volume_step if sym else 0.0,
        "fillingMode": "IOC",
        "stopsLevelPoints": sym.trade_stops_level if sym else 0,
        "mode": "observe",
        "agentVersion": AGENT_VERSION,
    }


def build_account() -> dict[str, Any] | None:
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "version": WIRE_VERSION,
        "type": "account.snapshot",
        "accountId": str(info.login),
        "time": now_ms(),
        "balance": info.balance,
        "equity": info.equity,
        "margin": info.margin,
        "freeMargin": info.margin_free,
        "currency": info.currency,
    }


def build_positions(symbol: str) -> dict[str, Any]:
    positions = mt5.positions_get(symbol=symbol) or ()
    mapped = []
    for p in positions:
        mapped.append(
            {
                "brokerPositionId": str(p.ticket),
                "symbol": p.symbol,
                # POSITION_TYPE_BUY == 0, POSITION_TYPE_SELL == 1
                "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "volume": p.volume,
                "entryPrice": p.price_open,
                "stopLoss": p.sl,
                "takeProfit": p.tp,
                "floatingPnl": p.profit,
            }
        )
    return {
        "version": WIRE_VERSION,
        "type": "positions.snapshot",
        "accountId": account_id(),
        "time": now_ms(),
        "positions": mapped,
    }


def build_tick(symbol: str) -> dict[str, Any] | None:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return {
        "version": WIRE_VERSION,
        "type": "market.tick",
        "accountId": account_id(),
        "time": now_ms(),
        "symbol": symbol,
        "bid": tick.bid,
        "ask": tick.ask,
    }


def build_candles(symbol: str, count: int) -> list[dict[str, Any]]:
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, count)
    if rates is None:
        return []
    acc = account_id()
    messages = []
    last_index = len(rates) - 1
    for i, r in enumerate(rates):
        messages.append(
            {
                "version": WIRE_VERSION,
                "type": "market.candle",
                "accountId": acc,
                "time": now_ms(),
                "symbol": symbol,
                "timeframe": TIMEFRAME_LABEL,
                "openTime": int(r["time"]) * 1000,
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": int(r["tick_volume"]),
                # only the most recent bar is still forming
                "closed": i != last_index,
            }
        )
    return messages


def build_heartbeat() -> dict[str, Any]:
    return {
        "version": WIRE_VERSION,
        "type": "agent.heartbeat",
        "accountId": account_id(),
        "time": now_ms(),
        "agentId": AGENT_ID,
        "latencyMs": 0,
    }


# --- Phase 09: SIMULATED execution (observe mode, no broker call, ever) ---

def _ack(command_id: str, status: str, reason: str | None) -> dict[str, Any]:
    return {
        "version": WIRE_VERSION,
        "type": "execution.ack",
        "accountId": account_id(),
        "time": now_ms(),
        "commandId": command_id,
        "status": status,  # ACCEPTED | REJECTED | DUPLICATE | EXPIRED
        "reason": reason,
    }


def _simulated_report(cmd: dict[str, Any], price: float | None) -> dict[str, Any]:
    return {
        "version": WIRE_VERSION,
        "type": "execution.report",
        "accountId": account_id(),
        "time": now_ms(),
        "commandId": cmd["id"],
        "status": "SIMULATED",
        "symbol": cmd["symbol"],
        "side": cmd["side"],
        "brokerOrderId": None,       # no broker order exists, by design
        "brokerPositionId": None,
        "filledVolume": cmd["volume"],
        "averagePrice": price,
        "brokerRetcode": None,
        "detail": f"SIMULATED {cmd['volume']} lot {cmd['side']} {cmd['symbol']} (observe mode, no broker order)",
    }


def validate_order_command(cmd: dict[str, Any], symbol: str) -> str | None:
    """Return a rejection reason, or None when the command is valid."""
    for field in ("id", "symbol", "side", "orderType", "volume", "sl", "expiresAt"):
        if field not in cmd or cmd[field] is None:
            return f"missing required field '{field}'"
    if EXECUTION_MODE != "observe":
        # Structurally unreachable (constant), kept as an explicit guard: an
        # absent/unknown/unexpected mode is always treated as refuse.
        return f"unsupported execution mode '{EXECUTION_MODE}'"
    if cmd["side"] not in ("BUY", "SELL"):
        return f"invalid side '{cmd['side']}'"
    if cmd["orderType"] != "MARKET":
        return f"unsupported orderType '{cmd['orderType']}' in this slice"
    if cmd["symbol"] != symbol:
        return f"symbol '{cmd['symbol']}' not served by this agent ({symbol})"
    if not isinstance(cmd["volume"], (int, float)) or cmd["volume"] <= 0:
        return "volume must be > 0"
    info = mt5.symbol_info(symbol)
    if info is not None:
        if cmd["volume"] < info.volume_min or cmd["volume"] > info.volume_max:
            return f"volume {cmd['volume']} outside [{info.volume_min}, {info.volume_max}]"
    if not isinstance(cmd["sl"], (int, float)) or cmd["sl"] <= 0:
        return "stop loss is mandatory (no trade without a stop)"
    return None


async def handle_command(send, raw: str, symbol: str) -> None:
    try:
        cmd = json.loads(raw)
    except json.JSONDecodeError:
        return  # unparseable frame: nothing to ack against
    if cmd.get("type") != "execution.order":
        return  # only order commands are understood in this slice

    command_id = cmd.get("id")
    if not command_id:
        await send(_ack("", "REJECTED", "missing command id"))
        return

    # Idempotency: same id seen before -> DUPLICATE ack, NO report.
    if command_id in _seen_command_ids:
        print(f"[observer] duplicate command {command_id} -> DUPLICATE ack")
        await send(_ack(command_id, "DUPLICATE", "command id already processed"))
        return

    # Expiry: refuse late commands, NO report.
    expires_at = cmd.get("expiresAt")
    if not isinstance(expires_at, (int, float)) or now_ms() > expires_at:
        _seen_command_ids.add(command_id)
        print(f"[observer] expired command {command_id} -> EXPIRED ack")
        await send(_ack(command_id, "EXPIRED", "command past expiresAt"))
        return

    reason = validate_order_command(cmd, symbol)
    if reason is not None:
        _seen_command_ids.add(command_id)
        print(f"[observer] rejected command {command_id}: {reason}")
        await send(_ack(command_id, "REJECTED", reason))
        return

    # Valid: ack, then the SIMULATED outcome. No broker call exists here.
    _seen_command_ids.add(command_id)
    tick = mt5.symbol_info_tick(symbol)
    price = (tick.ask if cmd["side"] == "BUY" else tick.bid) if tick else None
    print(f"[observer] SIMULATED {cmd['volume']} lot {cmd['side']} {symbol} (command {command_id})")
    await send(_ack(command_id, "ACCEPTED", None))
    await send(_simulated_report(cmd, price))


async def handler(websocket, symbol: str, candle_count: int) -> None:
    print(f"[observer] cockpit connected; streaming {symbol} ({EXECUTION_MODE} / no broker calls)")

    async def send(msg: dict[str, Any] | None) -> None:
        if msg is not None:
            await websocket.send(json.dumps(msg))

    async def produce() -> None:
        # Backfill: identity + snapshots + recent candles.
        await send(build_hello(symbol))
        await send(build_account())
        await send(build_positions(symbol))
        for candle in build_candles(symbol, candle_count):
            await send(candle)

        last_account = 0.0
        last_heartbeat = 0.0
        last_candle_refresh = 0.0
        while True:
            await send(build_tick(symbol))  # ~1 Hz

            now = time.time()
            if now - last_account >= 2:
                await send(build_account())
                await send(build_positions(symbol))
                last_account = now
            if now - last_heartbeat >= 3:
                await send(build_heartbeat())
                last_heartbeat = now
            if now - last_candle_refresh >= 15:
                # refresh the last few bars so the forming candle updates
                for candle in build_candles(symbol, 3):
                    await send(candle)
                last_candle_refresh = now

            await asyncio.sleep(1)

    async def consume() -> None:
        # Phase 09: receive execution.order commands from the gateway.
        async for raw in websocket:
            await handle_command(send, raw, symbol)

    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(produce())
            group.create_task(consume())
    except* websockets.ConnectionClosed:
        print("[observer] cockpit disconnected")


async def main() -> None:
    parser = argparse.ArgumentParser(description="MT5 observe-only producer")
    parser.add_argument("--symbol", default="XAUUSDm", help="broker symbol, e.g. XAUUSDm")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--candles", type=int, default=120, help="M15 candles to backfill")
    args = parser.parse_args()

    if not mt5.initialize():
        raise SystemExit(f"[observer] mt5.initialize() failed: {mt5.last_error()} "
                         f"(is the MT5 terminal open and logged in?)")

    if mt5.symbol_info(args.symbol) is None:
        mt5.shutdown()
        raise SystemExit(f"[observer] symbol {args.symbol!r} not found — check the exact name in Market Watch")
    mt5.symbol_select(args.symbol, True)

    info = mt5.account_info()
    print(f"[observer] attached to account {info.login} @ {info.company} ({info.server}), "
          f"balance={info.balance} {info.currency}")
    print(f"[observer] READ-ONLY / observe. Serving ws://{args.host}:{args.port}")

    async with websockets.serve(
        lambda ws: handler(ws, args.symbol, args.candles), args.host, args.port
    ):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[observer] stopped")
    finally:
        mt5.shutdown()
