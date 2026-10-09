"""The command line of the core: what it refuses, what it prints, and what it does to the database. The handlers are synchronous entry
points that run their own event loop, so these tests are synchronous too."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from pydantic import SecretStr

from trading_os.app.config import Settings
from trading_os.cli.candles import parse_candle
from trading_os.cli.main import build_parser, main, server_config
from trading_os.cli.terminal import ReadOnlyTerminal
from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.mt5.fake import FakeMt5
from trading_os.infrastructure.mt5.transport import InProcessTransport
from trading_os.shared.errors import ValidationFailed
from trading_os.shared.logging.setup import setup_logging


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch) -> Callable[[str | None], None]:
    """Hand the commands settings that never read the developer's real ``.env``."""

    def apply(url: str | None) -> None:
        settings = Settings(_env_file=None, database_url=SecretStr(url) if url else None)
        monkeypatch.setattr("trading_os.app.config.get_settings", lambda: settings)

    return apply


@pytest.fixture
def simulated_terminal(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeMt5]:
    terminal = FakeMt5.default()
    monkeypatch.setattr("trading_os.cli.terminal.open_terminal", lambda: ReadOnlyTerminal(InProcessTransport(terminal)))
    yield terminal


# ------------------------------------------------------------------------------------------------------ the parser


def test_every_command_is_documented_in_the_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["--help"])
    assert stop.value.code == 0
    text = capsys.readouterr().out
    for command in (
        "serve",
        "db",
        "import-candles",
        "export-history",
        "list-symbols",
        "spread-history",
        "weekly-review",
        "mcp",
    ):
        assert command in text, command
    assert "places an order" in text


def test_the_defaults_are_the_ones_the_tools_always_had() -> None:
    parser = build_parser()
    export = parser.parse_args(["export-history", "--symbol", "XAUUSDm"])
    assert (export.timeframe, export.bars, export.start, export.end, str(export.out)) == (
        "M15",
        26_000,
        None,
        None,
        "candles.jsonl",
    )
    assert parser.parse_args(["list-symbols"]).canonical == ["EURUSD", "GBPUSD", "XAUUSD"]
    spreads = parser.parse_args(["spread-history", "--start", "2026-08-31", "--end", "2026-09-26"])
    assert spreads.symbols == ["EURUSDm", "XAUUSDm"] and spreads.server_offset == 0.0
    assert str(parser.parse_args(["weekly-review"]).out_dir) == "weekly-reviews"


def test_an_unknown_command_or_a_missing_argument_is_a_usage_error() -> None:
    for argv in (
        ["fly"],
        [],
        ["db"],
        ["import-candles"],
        ["export-history"],
        ["spread-history", "--start", "2026-01-01"],
    ):
        with pytest.raises(SystemExit) as stop:
            main(argv)
        assert stop.value.code == 2, argv


# ------------------------------------------------------------------------------------------------------ what it refuses


def test_the_core_listens_on_this_machine_only(
    configure: Callable[[str | None], None], capsys: pytest.CaptureFixture[str]
) -> None:
    configure("postgresql://u@127.0.0.1:1/x")
    assert main(["serve", "--host", "0.0.0.0"]) == 2
    assert "not a loopback address" in capsys.readouterr().err


def test_serve_refuses_to_start_without_a_database(
    configure: Callable[[str | None], None], capsys: pytest.CaptureFixture[str]
) -> None:
    configure(None)
    assert main(["serve"]) == 2
    assert "DATABASE_URL is not configured" in capsys.readouterr().err


@pytest.fixture
def pristine_logging() -> Iterator[None]:
    """``setup_logging`` rewires the process: put every logger it (or uvicorn) touches back as it was."""
    names = ["", "uvicorn", "uvicorn.error", "uvicorn.access"]
    saved = [(logging.getLogger(n), list(logging.getLogger(n).handlers), logging.getLogger(n).level,
              logging.getLogger(n).propagate, logging.getLogger(n).disabled) for n in names]  # fmt: skip
    yield
    for logger, handlers, level, propagate, disabled in saved:
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate
        logger.disabled = disabled


def test_the_websocket_credential_never_reaches_the_log(
    pristine_logging: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The WebSocket carries its token in the query string, and uvicorn writes the handshake line — ``"WebSocket /ws?access_token=…"
    [accepted]`` — at INFO whatever ``access_log`` says. Its own logging set-up would replace our masked handler, so the core's
    configuration forbids it; this is checked through the real ``uvicorn.Config``, not through a flag."""
    secret = "tok-0123456789abcdef"
    setup_logging("INFO")
    config = server_config(object(), "127.0.0.1", 8000, "INFO")
    assert config.log_config is None and config.access_log is False
    logging.getLogger("uvicorn.error").info(
        '%s - "WebSocket %s" [accepted]', "127.0.0.1:5000", f"/ws?access_token={secret}"
    )
    written = capsys.readouterr().err
    assert "[accepted]" in written  # the line is still there: it is the credential that is not
    assert secret not in written and "access_token=***" in written


def test_a_destructive_script_needs_its_name_repeated(
    configure: Callable[[str | None], None], capsys: pytest.CaptureFixture[str]
) -> None:
    configure("postgresql://u@127.0.0.1:1/x")
    assert main(["db", "manual", "drop_legacy_tables", "--confirm", "yes"]) == 2
    assert "--confirm must repeat" in capsys.readouterr().err


def test_commands_that_need_the_database_say_so_instead_of_crashing(
    configure: Callable[[str | None], None], capsys: pytest.CaptureFixture[str]
) -> None:
    configure(None)
    for argv in (["db", "status"], ["db", "migrate"]):
        assert main(argv) == 2, argv
    assert capsys.readouterr().err.count("DATABASE_URL is not configured") == 2


# ------------------------------------------------------------------------------------------------------ the schema


@pytest.mark.db
def test_the_schema_is_migrated_reported_and_checked_for_drift(
    fresh_database_url: str, configure: Callable[[str | None], None], capsys: pytest.CaptureFixture[str]
) -> None:
    configure(fresh_database_url)
    assert main(["db", "migrate"]) == 0
    assert "up to date" in capsys.readouterr().out  # the template database is already migrated
    assert main(["db", "status"]) == 0
    out = capsys.readouterr().out
    assert "0001_baseline" in out and "0002_core" in out and "pending" not in out and "DRIFTED" not in out

    with psycopg.connect(fresh_database_url, autocommit=True) as connection:
        connection.execute("UPDATE schema_migrations SET checksum = 'edited-after-the-fact' WHERE version = '0002'")
    assert (
        main(["db", "status"]) == 1
    )  # an applied migration that was edited afterwards is an error, not a silent drift
    assert "DRIFTED" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------------ candles


def jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def row(minute: int, **changes: Any) -> dict[str, Any]:
    base = datetime(2026, 1, 5, 7, tzinfo=UTC).timestamp() * 1000 + minute * 60_000
    return {
        "symbol": "EURUSDm", "timeframe": "M1", "openTime": int(base), "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15,
        "volume": 120, "closed": True, **changes,
    }  # fmt: skip


def count(url: str) -> int:
    with psycopg.connect(url) as connection:
        found = connection.execute("SELECT count(*) FROM candles").fetchone()
    assert found is not None
    return int(found[0])


@pytest.mark.db
def test_candles_are_loaded_idempotently_and_a_changed_bar_is_updated(
    fresh_database_url: str, configure: Callable[[str | None], None], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(fresh_database_url)
    file = jsonl(tmp_path / "c.jsonl", [row(0), row(1), row(2)])
    assert main(["import-candles", str(file)]) == 0
    assert "upserted 3 candles" in capsys.readouterr().out and count(fresh_database_url) == 3
    jsonl(file, [row(0), row(1), row(2, close=1.18, closed=False), row(3)])
    assert main(["import-candles", str(file)]) == 0
    assert count(fresh_database_url) == 4  # the re-run added one bar and duplicated none
    with psycopg.connect(fresh_database_url) as connection:
        found = connection.execute("SELECT close, closed FROM candles ORDER BY open_time OFFSET 2 LIMIT 1").fetchone()
    assert found == (1.18, False)


@pytest.mark.db
def test_a_line_that_is_not_a_candle_stops_the_import_and_nothing_is_loaded(
    fresh_database_url: str, configure: Callable[[str | None], None], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(fresh_database_url)
    file = tmp_path / "broken.jsonl"
    file.write_text(json.dumps(row(0)) + "\n" + '{"symbol": "EURUSDm"}\n' + json.dumps(row(2)) + "\n", encoding="utf-8")
    assert main(["import-candles", str(file)]) == 2
    assert (
        "line 2" in capsys.readouterr().err and count(fresh_database_url) == 0
    )  # a half-read file is not loaded silently


def test_a_candle_line_is_read_back_as_the_bar_it_describes() -> None:
    candle = parse_candle(json.dumps(row(5, volume=77)), 1)
    assert (candle.symbol, candle.timeframe, candle.volume, candle.closed) == ("EURUSDm", Timeframe.M1, 77.0, True)
    assert candle.open_time == datetime(2026, 1, 5, 7, 5, tzinfo=UTC)
    with pytest.raises(ValidationFailed):
        parse_candle("not json", 9)


# ------------------------------------------------------------------------------------------------------ the terminal tools


def test_history_is_exported_as_the_lines_the_import_reads(
    simulated_terminal: FakeMt5, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "h.jsonl"
    assert main(["export-history", "--symbol", "EURUSDm", "--timeframe", "M5", "--bars", "30", "--out", str(out)]) == 0
    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 30 and {line["timeframe"] for line in lines} == {"M5"}
    assert [line["closed"] for line in lines] == [True] * 29 + [False]  # only the newest bar may still be forming
    assert all(isinstance(line["openTime"], int) and isinstance(line["volume"], int) for line in lines)
    assert "wrote 30 candles" in capsys.readouterr().out
    assert parse_candle(json.dumps(lines[0]), 1).symbol == "EURUSDm"  # (and `import-candles` reads exactly this)


def test_a_range_is_exported_exactly_from_inclusive_to_exclusive(simulated_terminal: FakeMt5, tmp_path: Path) -> None:
    out = tmp_path / "r.jsonl"
    argv = ["export-history", "--symbol", "EURUSDm", "--timeframe", "M15", "--out", str(out)]
    assert main([*argv, "--from", "2026-01-05T08:00:00Z", "--to", "2026-01-05T09:00:00Z"]) == 0
    times = [json.loads(line)["openTime"] for line in out.read_text(encoding="utf-8").splitlines()]
    expected = [int(datetime(2026, 1, 5, 8, m, tzinfo=UTC).timestamp()) * 1000 for m in (0, 15, 30, 45)]
    assert times == expected  # 09:00 itself is excluded, and every bar of a historical range is closed
    assert all(json.loads(line)["closed"] for line in out.read_text(encoding="utf-8").splitlines())


def test_the_export_refuses_an_unknown_symbol_and_a_half_range(
    simulated_terminal: FakeMt5, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = str(tmp_path / "x.jsonl")
    assert main(["export-history", "--symbol", "NOPE", "--out", out]) == 2
    assert "not found in the terminal" in capsys.readouterr().err
    assert main(["export-history", "--symbol", "EURUSDm", "--from", "2026-01-05", "--out", out]) == 2
    assert "--from and --to must be given together" in capsys.readouterr().err
    assert (
        main(["export-history", "--symbol", "EURUSDm", "--from", "2026-01-06", "--to", "2026-01-05", "--out", out]) == 2
    )


def test_the_symbols_behind_a_canonical_name_are_listed_with_what_a_registry_needs(
    simulated_terminal: FakeMt5, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list-symbols", "--canonical", "EURUSD", "XAUUSD", "USDJPY"]) == 0
    out = capsys.readouterr().out
    assert "# EURUSD -> EURUSDm" in out and "# XAUUSD -> XAUUSDm" in out and "no matching broker symbol found" in out
    assert "digits" in out and "trade_tick_value" in out and "volume_step" in out and "trade_stops_level" in out


def test_a_terminal_that_cannot_be_attached_is_reported_not_traced(
    simulated_terminal: FakeMt5, capsys: pytest.CaptureFixture[str]
) -> None:
    simulated_terminal.initialize_fails = True
    assert main(["list-symbols"]) == 2
    assert "could not be attached" in capsys.readouterr().err


def test_the_event_loop_helper_runs_a_coroutine_on_a_selector_loop() -> None:
    from trading_os.cli.main import run

    async def which() -> str:
        return type(asyncio.get_running_loop()).__name__

    assert "Selector" in run(which())
