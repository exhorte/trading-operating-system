"""``python -m trading_os`` — the command line of the core.

    serve                       run the core: API, WebSocket, engine (loopback only)
    db migrate | status | manual    the database schema
    import-candles FILE         load candles (JSON Lines) into the database
    export-history              export candles from the running MT5 terminal (read-only)
    list-symbols                the broker symbols behind canonical names (read-only)
    spread-history              the spread per New York window from the broker's tick history (read-only)
    weekly-review               a Markdown review of a week, from the journal
    mcp                         the read-only MCP server (needs the ``mcp`` extra)
    gen-types                   generate the cockpit's TypeScript types from the core's own schemas

Nothing here places an order, arms the autonomy or changes a rule: those are gestures a person makes in the cockpit.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trading_os.domain.primitives import Timeframe
from trading_os.shared.errors import TradingOsError, ValidationFailed

if TYPE_CHECKING:
    import uvicorn

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def run[T](coroutine: Awaitable[T]) -> T:
    """Run ``coroutine`` on a Selector loop: psycopg's async mode cannot run on Windows' default Proactor loop, and nothing in the core
    needs a Proactor-only feature (the MT5 worker is driven through threads)."""

    async def wrapper() -> T:
        return await coroutine

    return asyncio.run(wrapper(), loop_factory=asyncio.SelectorEventLoop)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading_os", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    serve = commands.add_parser("serve", help="run the core (loopback only)")
    serve.add_argument("--host", help="default: API_HOST (127.0.0.1). Only a loopback address is accepted")
    serve.add_argument("--port", type=int, help="default: API_PORT (8000)")
    serve.set_defaults(handler=_serve)

    db = commands.add_parser("db", help="the database schema").add_subparsers(dest="db_command", required=True)
    migrate = db.add_parser("migrate", help="apply the pending migrations")
    migrate.add_argument("--target", help="stop after this version, e.g. 0002")
    migrate.set_defaults(handler=_db_migrate)
    db.add_parser("status", help="which migrations are applied, pending or drifted").set_defaults(handler=_db_status)
    manual = db.add_parser("manual", help="run ONE destructive script from migrations/manual (a human decision)")
    manual.add_argument("name")
    manual.add_argument("--confirm", required=True, help="repeat the script's name to confirm")
    manual.set_defaults(handler=_db_manual)

    imp = commands.add_parser("import-candles", help="load candles (JSON Lines) into the database")
    imp.add_argument("file", type=Path)
    imp.set_defaults(handler=_import_candles)

    export = commands.add_parser("export-history", help="export candles from the running MT5 terminal as JSON Lines")
    export.add_argument("--symbol", required=True, help="the broker's name, e.g. XAUUSDm")
    export.add_argument("--timeframe", default="M15", choices=[t.value for t in Timeframe])
    export.add_argument("--bars", type=int, default=26_000, help="the last N bars (ignored with --from/--to)")
    export.add_argument("--from", dest="start", help="inclusive UTC bound, e.g. 2024-06-01T00:00:00Z")
    export.add_argument("--to", dest="end", help="EXCLUSIVE UTC bound, e.g. 2025-06-06T13:30:00Z")
    export.add_argument("--out", type=Path, default=Path("candles.jsonl"))
    export.set_defaults(handler=_export_history)

    symbols = commands.add_parser("list-symbols", help="the broker symbols behind canonical names (read-only)")
    symbols.add_argument("--canonical", nargs="+", default=["EURUSD", "GBPUSD", "XAUUSD"])
    symbols.set_defaults(handler=_list_symbols)

    spreads = commands.add_parser(
        "spread-history", help="the spread per New York window from the tick history (read-only)"
    )
    spreads.add_argument("--symbols", nargs="+", default=["EURUSDm", "XAUUSDm"], help="broker names")
    spreads.add_argument("--start", required=True, help="UTC date YYYY-MM-DD, inclusive")
    spreads.add_argument("--end", required=True, help="UTC date YYYY-MM-DD, exclusive")
    spreads.add_argument("--server-offset", type=float, default=0.0, help="server clock minus UTC, hours (Exness: 0)")
    spreads.set_defaults(handler=_spread_history)

    review = commands.add_parser("weekly-review", help="a Markdown review of a week, from the journal")
    review.add_argument("--account", help="default: ACTIVE_ACCOUNT_ID")
    review.add_argument("--from", dest="start", help="UTC date or time; default: a week before --to")
    review.add_argument("--to", dest="end", help="UTC date or time; default: now")
    review.add_argument("--out-dir", type=Path, default=Path("weekly-reviews"))
    review.set_defaults(handler=_weekly_review)

    commands.add_parser("mcp", help="the read-only MCP server on stdio").set_defaults(handler=_mcp)

    types = commands.add_parser("gen-types", help="generate the cockpit's TypeScript types (lib/api/generated.ts)")
    types.add_argument("--out", type=Path, help="default: lib/api/generated.ts at the repository root")
    types.add_argument("--check", action="store_true", help="write nothing; exit 1 when the file on disk is stale")
    types.set_defaults(handler=_gen_types)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # A console (or a pipe) that cannot encode an arrow or a dash must not turn a report into a crash.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except TradingOsError as error:
        print(f"error: {error.safe_message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


# ------------------------------------------------------------------------------------------------------ handlers


def _database_url() -> str:
    from trading_os.app.config import get_settings

    url = get_settings().database_url
    if url is None:
        raise ValidationFailed(
            "DATABASE_URL is not configured (scripts/start.ps1 writes it to .env)", code="database_not_configured"
        )
    return url.get_secret_value()


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from trading_os.app.config import get_settings
    from trading_os.app.main import create_app
    from trading_os.shared.logging.setup import setup_logging

    settings = get_settings()
    host = args.host or settings.api_host
    port = args.port or settings.api_port
    if host not in LOOPBACK:
        raise ValidationFailed(
            f"{host!r} is not a loopback address: the core listens on this machine only", code="not_loopback"
        )
    if settings.database_url is None:
        raise ValidationFailed(
            "DATABASE_URL is not configured (scripts/start.ps1 writes it to .env)", code="database_not_configured"
        )
    setup_logging(settings.log_level)
    if settings.trading_os_cockpit_token is None:
        print(
            "warning: TRADINGOS_COCKPIT_TOKEN is not set — every request but /api/system/health will be refused",
            file=sys.stderr,
        )
    run(uvicorn.Server(server_config(create_app(settings), host, port, settings.log_level)).serve())
    return 0


def server_config(app: Any, host: str, port: int, level: str) -> uvicorn.Config:
    """The uvicorn configuration of the core. Two settings are deliberate, both about the WebSocket's credential, which travels in
    the query string (a browser cannot set a header on a WebSocket):

    * ``access_log=False`` — the access line prints the URL;
    * ``log_config=None`` — uvicorn's own logging set-up would replace the masked handler ``setup_logging`` installed, and its
      handshake line (``"WebSocket /ws?access_token=…" [accepted]``) is not an access line: it is written at INFO, whatever
      ``access_log`` says."""
    import uvicorn

    return uvicorn.Config(
        app, host=host, port=port, log_level=level.lower(), access_log=False, log_config=None, loop="none"
    )


def _db_migrate(args: argparse.Namespace) -> int:
    from trading_os.infrastructure.database.migrate import migrate

    applied = run(migrate(_database_url(), target=args.target))
    print(f"applied: {', '.join(applied)}" if applied else "nothing to apply: the schema is up to date")
    return 0


def _db_status(args: argparse.Namespace) -> int:
    from trading_os.infrastructure.database.migrate import status

    rows = run(status(_database_url()))
    for row in rows:
        state = "DRIFTED" if row.drifted else ("applied" if row.applied else "pending")
        print(f"{row.version}_{row.name:<24} {state}")
    return 1 if any(r.drifted for r in rows) else 0


def _db_manual(args: argparse.Namespace) -> int:
    from trading_os.infrastructure.database.migrate import run_manual

    if args.confirm != args.name:
        raise ValidationFailed(
            "--confirm must repeat the script's name: this changes data and is not undone", code="not_confirmed"
        )
    run(run_manual(_database_url(), args.name))
    print(f"ran manual script {args.name}")
    return 0


def _with_repositories[T](work: Callable[[Any], Awaitable[T]]) -> T:
    from trading_os.infrastructure.database.pool import Database
    from trading_os.infrastructure.database.repositories import Repositories

    async def go() -> T:
        db = Database(_database_url())
        await db.open()
        try:
            return await work(Repositories.create(db))
        finally:
            await db.close()

    return run(go())


def _import_candles(args: argparse.Namespace) -> int:
    from trading_os.cli.candles import import_candles

    async def work(repos: Any) -> int:
        total = await import_candles(repos, args.file)
        row = await repos.market._db.fetch_one(
            "SELECT count(*) AS n, min(open_time) AS oldest, max(open_time) AS newest FROM candles"
        )
        print(f"upserted {total} candles; the table now holds {row['n']} rows, {row['oldest']} → {row['newest']}")
        return total

    _with_repositories(work)
    return 0


def _export_history(args: argparse.Namespace) -> int:
    from trading_os.cli.history import export_history, parse_utc
    from trading_os.cli.terminal import open_terminal

    async def go() -> None:
        async with open_terminal() as terminal:
            result = await export_history(
                terminal, symbol=args.symbol, timeframe=Timeframe(args.timeframe), out=args.out, bars=args.bars,
                start=parse_utc(args.start) if args.start else None, end=parse_utc(args.end) if args.end else None,
            )  # fmt: skip
        note = "" if result.offset_known else " (the broker clock could not be measured — read as UTC)"
        print(
            f"wrote {result.written} candles to {args.out} ({args.symbol} {args.timeframe}, {result.oldest} → {result.newest}){note}"
        )

    run(go())
    return 0


def _list_symbols(args: argparse.Namespace) -> int:
    from trading_os.cli.history import list_symbols
    from trading_os.cli.terminal import open_terminal

    async def go() -> None:
        async with open_terminal() as terminal:
            for line in await list_symbols(terminal, args.canonical):
                print(line)

    run(go())
    return 0


def _spread_history(args: argparse.Namespace) -> int:
    from trading_os.cli.history import parse_utc
    from trading_os.cli.spreads import render, report_symbol
    from trading_os.cli.terminal import open_terminal

    async def go() -> None:
        async with open_terminal() as terminal:
            summary = await terminal.account_summary()
            print(
                f"READ-ONLY. account trade_mode={summary['trade_mode']} server={summary['server']} currency={summary['currency']}"
            )
            for name in args.symbols:
                await terminal.select(name)
                report = await report_symbol(
                    terminal, name, parse_utc(args.start), parse_utc(args.end), args.server_offset
                )
                if report is None:
                    candidates = [row.get("name") for row in await terminal.symbols_like(name)]
                    print(f"warning: {name!r} is not a broker symbol; candidates: {candidates or 'none'}")
                    continue
                print("\n".join(render(report)))

    run(go())
    return 0


def _weekly_review(args: argparse.Namespace) -> int:
    from datetime import UTC, datetime

    from trading_os.app.config import get_settings
    from trading_os.app.container import build_container
    from trading_os.cli.history import parse_utc
    from trading_os.cli.weekly_review import compute_weekly_stats, render_weekly_review

    settings = get_settings()
    account_id = args.account or settings.active_account_id
    if account_id is None:
        raise ValidationFailed("name the account with --account, or set ACTIVE_ACCOUNT_ID", code="no_account")
    end = parse_utc(args.end) if args.end else datetime.now(UTC)
    start = parse_utc(args.start) if args.start else end - timedelta(days=7)

    async def go() -> str:
        container = build_container(settings)
        await container.db.open()
        try:
            trades = await container.journal.trades(account_id, start, end)
            summary = await container.journal.compliance(account_id, start, end)
        finally:
            await container.db.close()
        stats = compute_weekly_stats(start, end, trades, summary)
        print(
            f"weekly review computed: {stats.trade_count} trade(s), compliance {stats.compliance_rate:.0%}",
            file=sys.stderr,
        )
        return render_weekly_review(stats)

    markdown = run(go())
    args.out_dir.mkdir(parents=True, exist_ok=True)
    target = args.out_dir / f"{end:%Y-%m-%d}.md"
    target.write_text(markdown, encoding="utf-8")
    print(f"written to {target}", file=sys.stderr)
    return 0


def _mcp(args: argparse.Namespace) -> int:
    from trading_os.mcp.server import main as run_server

    return run_server()


def _gen_types(args: argparse.Namespace) -> int:
    from trading_os.devtools import gen

    out: Path = args.out or gen.DEFAULT_OUT
    if args.check:
        stale = gen.is_stale(out)
        print(f"{out}: {'STALE — run `python -m trading_os gen-types`' if stale else 'up to date'}")
        return 1 if stale else 0
    print(f"wrote {gen.write(out)} lines to {out}")
    return 0
