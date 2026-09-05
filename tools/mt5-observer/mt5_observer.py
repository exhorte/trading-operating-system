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
from datetime import datetime, timezone
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

# T02b/T05: brokerPositionId is POSITION_IDENTIFIER (TradePosition.identifier
# / TradeDeal.position_id) — NOT TradePosition.ticket. The identifier "does
# not change during the life of a position" (MT5 docs); ticket is the
# opening order's ticket and can be rewritten by broker-side service
# operations. They coincide almost always, which is exactly what made the
# bug invisible: the day they diverge on a still-open position, a ticket-keyed
# diff sees one id vanish and another appear — a false close, a false open,
# tradesToday incremented for a trade that never happened, a phantom entry
# in the consecutive-loss streak, and an entry capture for a trade that
# hasn't started. Use `.identifier` everywhere a position is keyed, and
# `position=` in history_deals_get must be that same identifier.
_known_position_ids: set[int] = set()

# T05: epoch ms of the last missed-round-trip deal scan (see
# scan_missed_round_trips) — 0 means "never scanned yet".
_last_deal_scan_ms: int = 0


def now_ms() -> int:
    return int(time.time() * 1000)


def account_id() -> str:
    info = mt5.account_info()
    return str(info.login) if info else "unknown"


def resolve_server_utc_offset_minutes(symbol: str) -> int:
    """MT5 tick timestamps are epoch seconds but represent the broker's
    server/display time, not true UTC (a known MT5 quirk) — comparing one to
    the system's real UTC clock reveals the broker's offset. Rounded to the
    nearest 30 minutes: real broker offsets are always half-hour-aligned, and
    the raw difference otherwise carries clock-drift/latency noise.

    T02a (trading-day anchor): re-resolved every time build_hello() is called
    (agent.hello is re-sent on every gateway reconnect) so a DST transition
    is picked up without ever hardcoding an offset.
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return 0
    offset_seconds = tick.time - time.time()
    return round(offset_seconds / 60 / 30) * 30


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
        "serverUtcOffsetMinutes": resolve_server_utc_offset_minutes(symbol),
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


def _map_position(p: Any) -> dict[str, Any]:
    return {
        "brokerPositionId": str(p.identifier),
        "symbol": p.symbol,
        # POSITION_TYPE_BUY == 0, POSITION_TYPE_SELL == 1
        "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
        "volume": p.volume,
        "entryPrice": p.price_open,
        "stopLoss": p.sl,
        "takeProfit": p.tp,
        "floatingPnl": p.profit,
    }


def build_positions_snapshot(positions: Any) -> dict[str, Any]:
    return {
        "version": WIRE_VERSION,
        "type": "positions.snapshot",
        "accountId": account_id(),
        "time": now_ms(),
        "positions": [_map_position(p) for p in positions],
    }


def build_position_opened(p: Any) -> dict[str, Any]:
    """T05: a genuinely new position (keyed by identifier, see module docstring
    on _known_position_ids). openedAt is detection time, not MT5's true fill
    time — the wire has never carried that (T02a limitation, unchanged by
    this move to server-side detection: positions.snapshot still has no real
    open timestamp field)."""
    return {
        "version": WIRE_VERSION,
        "type": "position.opened",
        "accountId": account_id(),
        "time": now_ms(),
        "brokerPositionId": str(p.identifier),
        "symbol": p.symbol,
        "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
        "volume": p.volume,
        "entryPrice": p.price_open,
        "stopLoss": p.sl,
        "takeProfit": p.tp,
        "openedAt": now_ms(),
    }


def build_position_opened_from_deal(position_id: int, entry_deal: Any) -> dict[str, Any]:
    """T05: reconstructs the opened side of a position that opened AND closed
    between two polls (see scan_missed_round_trips) — never seen live via
    positions_get(), so this is built from its entry deal alone. stopLoss/
    takeProfit are 0.0: MT5 deal records carry no SL/TP fields at all, and
    0.0 is MT5's own "no stop set" convention for a position — not a
    fabricated guess, and any rendered capture makes it obvious (a stop at
    price 0 on an XAUUSD chart cannot be mistaken for a real level).
    Unlike the live-detection path, openedAt here IS the real MT5 fill time
    (the entry deal's own timestamp), not a detection-time approximation.
    """
    return {
        "version": WIRE_VERSION,
        "type": "position.opened",
        "accountId": account_id(),
        "time": now_ms(),
        "brokerPositionId": str(position_id),
        "symbol": entry_deal.symbol,
        "side": "BUY" if entry_deal.type == mt5.DEAL_TYPE_BUY else "SELL",
        "volume": entry_deal.volume,
        "entryPrice": entry_deal.price,
        "stopLoss": 0.0,
        "takeProfit": 0.0,
        "openedAt": entry_deal.time * 1000,
    }


def diff_position_ids(known_ids: set[int], current_ids: set[int]) -> tuple[set[int], set[int]]:
    """Pure: (opened_ids, closed_ids) from one before/after comparison.
    Deliberately does not special-case an empty `known_ids` — callers decide
    whether a given poll is a real diff or a baseline-seeding read (see
    seed_known_positions vs poll_positions)."""
    return current_ids - known_ids, known_ids - current_ids


def sum_realized_pnl(deals: Any) -> float:
    """Net P&L of a closed position across ALL its deals (entry + every exit).

    T02b pitfall (flagged in review): a position can close in several partial
    deals. Judging the outcome from a single deal — e.g. the last partial
    close, which can be marginally negative after swap even though the
    position was net profitable — misclassifies a winner as a loser. Summing
    profit + commission + swap over the whole deal history is the only
    correct net.
    """
    return round(sum(d.profit + d.commission + d.swap for d in deals), 2)


def weighted_exit_price(exit_deals: Any) -> float:
    """Volume-weighted average fill price across every exit deal (T05: a
    partial close in several fills has no single 'the' exit price)."""
    total_volume = sum(d.volume for d in exit_deals)
    if total_volume <= 0:
        return exit_deals[0].price if len(exit_deals) > 0 else 0.0
    return round(sum(d.price * d.volume for d in exit_deals) / total_volume, 5)


def build_position_closed(position_id: int, deals: Any) -> dict[str, Any] | None:
    """None when the deal history for this position isn't available yet (a
    disconnect racing the close) — callers must not emit a half-known fact.
    `position_id` is POSITION_IDENTIFIER == TradeDeal.position_id (see module
    docstring on _known_position_ids) — every deal in `deals` is expected to
    carry that same position_id, which is exactly what
    history_deals_get(position=position_id) guarantees."""
    entry_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
    exit_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
    if not entry_deals or not exit_deals:
        return None
    entry = entry_deals[0]
    return {
        "version": WIRE_VERSION,
        "type": "position.closed",
        "accountId": account_id(),
        "time": now_ms(),
        "brokerPositionId": str(position_id),
        "symbol": entry.symbol,
        "side": "BUY" if entry.type == mt5.DEAL_TYPE_BUY else "SELL",
        "volume": round(sum(d.volume for d in entry_deals), 2),
        "realizedPnl": sum_realized_pnl(deals),
        # T05: needed to mark the exit fill on a rendered capture.
        "exitPrice": weighted_exit_price(exit_deals),
        "closedAt": max(d.time for d in exit_deals) * 1000,
    }


def seed_known_positions(symbol: str) -> dict[str, Any]:
    """First-ever read for this run: establishes the opened/closed baseline
    without emitting any lifecycle event for positions already open before
    this observer started (T02b's original comment on this, now shared with
    T05's opened side: neither must fire on boot). Also starts the clock for
    scan_missed_round_trips so the very first poll doesn't scan the account's
    entire deal history."""
    global _known_position_ids, _last_deal_scan_ms
    current = mt5.positions_get(symbol=symbol) or ()
    _known_position_ids = {p.identifier for p in current}
    _last_deal_scan_ms = now_ms()
    return build_positions_snapshot(current)


def scan_missed_round_trips(
    known_before_this_poll: set[int], current_ids: set[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """T05 — closes a real hole in poll_positions's snapshot diff: a position
    that opens AND fully closes between two 2s polls (a stop hit instantly in
    a fast market, a short scalp) never appears in `_known_position_ids` at
    all, so diff_position_ids can never report it as closed either — no
    opened event, no closed event, no capture, no entry in tradesToday or the
    consecutive-loss streak. These are exactly the trades that matter most
    for discipline metrics.

    Fix: independently scan exit deals since the last poll. A position_id
    with a recent exit deal that was never in `known_before_this_poll` and
    isn't in `current_ids` (i.e. genuinely fully closed, not a partial close
    on a still-open position) is a missed round trip — reconstruct both its
    opened and closed messages from deal history alone.
    """
    global _last_deal_scan_ms
    since_ms = _last_deal_scan_ms
    until_ms = now_ms()
    _last_deal_scan_ms = until_ms
    if since_ms >= until_ms:
        return [], []

    recent = mt5.history_deals_get(
        datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc),
        datetime.fromtimestamp(until_ms / 1000, tz=timezone.utc),
    ) or ()
    recently_exited_ids = {d.position_id for d in recent if d.entry == mt5.DEAL_ENTRY_OUT}
    missed_ids = recently_exited_ids - known_before_this_poll - current_ids

    opened_messages = []
    closed_messages = []
    for position_id in missed_ids:
        deals = mt5.history_deals_get(position=position_id) or ()
        entry_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
        if not entry_deals:
            continue  # entry deal not synced yet — never emit a half-known fact
        closed_msg = build_position_closed(position_id, deals)
        if closed_msg is None:
            continue
        opened_messages.append(build_position_opened_from_deal(position_id, entry_deals[0]))
        closed_messages.append(closed_msg)
    return opened_messages, closed_messages


def poll_positions(symbol: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """One positions_get() call per tick: the live snapshot, every
    position.opened (T05) and position.closed (T02b) since the previous
    poll — both sides of the same diff_position_ids comparison, PLUS any
    round trip missed entirely by that diff (scan_missed_round_trips). Never
    call this for the very first read of a run; use seed_known_positions
    instead.
    """
    global _known_position_ids
    known_before_this_poll = _known_position_ids
    current = mt5.positions_get(symbol=symbol) or ()
    current_ids = {p.identifier for p in current}
    opened_ids, closed_ids = diff_position_ids(known_before_this_poll, current_ids)
    _known_position_ids = current_ids

    by_identifier = {p.identifier: p for p in current}
    opened_messages = [build_position_opened(by_identifier[i]) for i in opened_ids]

    closed_messages = []
    for position_id in closed_ids:
        deals = mt5.history_deals_get(position=position_id) or ()
        msg = build_position_closed(position_id, deals)
        if msg is not None:
            closed_messages.append(msg)

    missed_opened, missed_closed = scan_missed_round_trips(known_before_this_poll, current_ids)
    opened_messages.extend(missed_opened)
    closed_messages.extend(missed_closed)

    return build_positions_snapshot(current), opened_messages, closed_messages


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
        await send(seed_known_positions(symbol))  # baseline: never fires opened/closed on boot
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
                snapshot, opened, closed = poll_positions(symbol)
                await send(snapshot)
                for msg in opened:
                    print(f"[observer] position {msg['brokerPositionId']} opened, "
                          f"entryPrice={msg['entryPrice']}")
                    await send(msg)
                for msg in closed:
                    print(f"[observer] position {msg['brokerPositionId']} closed, "
                          f"realizedPnl={msg['realizedPnl']}")
                    await send(msg)
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
