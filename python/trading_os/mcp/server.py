"""The MCP server — read-only tools over the trader's own data, on stdio (ADR 0005).

``python -m trading_os mcp`` (needs the ``mcp`` extra). Every tool is declared read-only, closed-world and idempotent; the tools
themselves live in ``tools.py`` and can only read. The server writes nothing to stdout but protocol messages: diagnostics go to stderr.

Register it by hand in the assistant's configuration — this project never writes into a user's MCP settings::

    {"mcpServers": {"trading-os": {"command": "<venv>\\\\Scripts\\\\python.exe", "args": ["-m", "trading_os", "mcp"],
                                   "env": {"ACTIVE_ACCOUNT_ID": "<account id>"}}}}
"""

from __future__ import annotations

import json
import sys
from collections.abc import Awaitable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from trading_os import __version__
from trading_os.mcp.tools import ReadOnlyTools
from trading_os.shared.errors import TradingOsError

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
INSTRUCTIONS = (
    "Read-only access to the trader's own data: closed trades, lockouts, candles, S01's evaluations, reconciliation findings, "
    "compliance. Nothing here writes, and nothing computes a performance figure — these are facts to reason from, not a verdict."
)


def as_text(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


async def answer(work: Awaitable[Any]) -> str:
    """A failure the core anticipated (a malformed date, no account configured …) reaches the assistant as a clear message it can act
    on; anything else is a crash whose text stays on the server (the SDK withholds it)."""
    try:
        return as_text(await work)
    except TradingOsError as error:
        raise ToolError(error.safe_message) from error


def build_server(tools: ReadOnlyTools) -> MCPServer:
    server = MCPServer("trading-os", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(name="get_trades", title="Get closed trades", annotations=READ_ONLY)
    async def get_trades(start: str, end: str, symbol: str | None = None) -> str:
        """Closed trades in a date range, with realised P&L, entry/exit, whether the entry levels are on record, the R multiple and the rules each broke.
        Facts only — no expectancy or win rate is computed. start/end: YYYY-MM-DD or ISO 8601; symbol: a broker symbol, e.g. EURUSDm."""
        return await answer(tools.get_trades(start, end, symbol))

    @server.tool(name="get_lockouts", title="Get lockout history", annotations=READ_ONLY)
    async def get_lockouts(until: str) -> str:
        """Every risk lockout window (kill switch, daily loss guard, consecutive-loss pause) up to a point in time (ISO 8601)."""
        return await answer(tools.get_lockouts(until))

    @server.tool(name="get_candles", title="Get candles", annotations=READ_ONLY)
    async def get_candles(symbol: str, timeframe: str, start: str, end: str) -> str:
        """OHLC candles for a broker symbol and timeframe (M1, M5, M15, H1, H4, D1 …) in a range, as stored — raw price history,
        never a signal or a level. At most 20 000 candles."""
        return await answer(tools.get_candles(symbol, timeframe, start, end))

    @server.tool(name="get_setup_proposals", title="Get S01 evaluations", annotations=READ_ONLY)
    async def get_setup_proposals(since: str) -> str:
        """Strategy S01's evaluations since a time (ISO 8601): 'proposed' (a candidate setup was detected) and 'blocked' (the stage where
        the sequence stopped). The measurement instrument (ADR 0011), never a signal to act on."""
        return await answer(tools.get_setup_proposals(since))

    @server.tool(name="get_execution_divergence", title="Get execution divergence", annotations=READ_ONLY)
    async def get_execution_divergence() -> str:
        """What the reconciliation found over the last seven days: commands still in doubt, commands settled from the broker's own
        history, and mismatches between the database and the broker."""
        return await answer(tools.get_execution_divergence())

    @server.tool(name="get_compliance_violations", title="Get compliance violations", annotations=READ_ONLY)
    async def get_compliance_violations(start: str, end: str) -> str:
        """Violations of the rules per closed trade in a range (trade during a lockout, outside the session) and the compliance rate.
        Recomputed from the facts on every call. The size policy is skipped: it needs the live balance, which this reader does not have."""
        return await answer(tools.get_compliance_violations(start, end))

    return server


def main() -> int:
    """Build the core's services without starting any of them, open the database, serve on stdio, close."""
    from trading_os.app.config import get_settings
    from trading_os.app.container import build_container
    from trading_os.cli.main import run

    settings = get_settings()
    container = build_container(settings)
    account_id = settings.active_account_id
    tools = ReadOnlyTools(
        repos=container.repos, journal=container.journal, clock=container.clock, account_id=lambda: account_id
    )
    server = build_server(tools)

    async def serve() -> None:
        await container.db.open()
        try:
            print("Trading OS MCP server running on stdio.", file=sys.stderr)
            await server.run_stdio_async()
        finally:
            await container.db.close()

    run(serve())
    return 0
