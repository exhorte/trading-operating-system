"""``validate`` (ADR 0026): candles from the database in, a report and a ledger line out."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.support.harness import Harness
from tests.unit.domain.validation.test_bench import COSTS, scenario_set, window
from trading_os.cli.main import build_parser
from trading_os.cli.validate import build_settings, read_ledger, render_markdown, strategy_definition, validate
from trading_os.domain.strategy.s01.proposal import S01_VARIANT
from trading_os.domain.validation.report import run_validation
from trading_os.infrastructure.database.pool import Database
from trading_os.shared.errors import ValidationFailed

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def test_the_two_strategies_are_known_and_nothing_else() -> None:
    assert strategy_definition("S01")[1] is S01_VARIANT
    assert strategy_definition("S02")[1] is not S01_VARIANT and strategy_definition("S02")[2] == "1"
    with pytest.raises(ValidationFailed):
        strategy_definition("S03")


def test_the_command_exists_and_takes_exactly_one_strategy() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "validate",
            "--strategy",
            "S02",
            "--symbol",
            "EURUSDm",
            "--from",
            "2026-09-11",
            "--to",
            "2026-09-18",
            "--spread",
            "0.00008",
        ]
    )
    assert args.strategy == "S02" and args.spread == 0.00008 and args.risk_percent == 1.0
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["validate", "--strategy", "S01", "S02", "--symbol", "x", "--from", "a", "--to", "b", "--spread", "1"]
        )


def test_the_markdown_leads_with_what_must_be_read_first() -> None:
    start, end = window(scenario_set().m1)
    settings, variant = build_settings(
        strategy_id="S01",
        symbol="EURUSD",
        start=start,
        end=end,
        costs=COSTS,
        risk_percent=1.0,
        cost_threshold=0.25,
        digits=5,
    )
    report = run_validation(scenario_set(), settings, variant, now=NOW)
    text = render_markdown(report)
    assert (
        text.index("À lire d'abord") < text.index("Résultat") and "Non modélisé" in text and report.fingerprint in text
    )
    assert "ni une preuve ni une prévision" in text


@pytest.mark.db
async def test_a_run_reads_the_database_writes_the_report_and_counts_the_look(db: Database, tmp_path: Path) -> None:
    h = Harness.create(db)
    data = scenario_set()
    start, end = window(data.m1)
    await h.repos.market.upsert_candles([c for c in [*data.m1, *data.h1, *data.h4, *data.d1]])
    settings, variant = build_settings(
        strategy_id="S01", symbol="EURUSD", start=start, end=end + timedelta(hours=1), costs=COSTS, risk_percent=1.0,
        cost_threshold=0.25, digits=5,
    )  # fmt: skip
    report, paths = await validate(h.repos, settings=settings, variant=variant, out_dir=tmp_path, now=NOW)
    assert report.evaluated_candles > 0 and all(path.exists() for path in paths)
    assert json.loads(paths[0].read_text(encoding="utf-8"))["fingerprint"] == report.fingerprint
    assert len(read_ledger(tmp_path / "ledger.jsonl")) == 1
    again, _ = await validate(h.repos, settings=settings, variant=variant, out_dir=tmp_path, now=NOW)
    assert again.previous_looks == 1 and len(read_ledger(tmp_path / "ledger.jsonl")) == 2


@pytest.mark.db
async def test_without_candles_there_is_nothing_to_measure(db: Database, tmp_path: Path) -> None:
    h = Harness.create(db)
    start = datetime(2026, 9, 11, tzinfo=UTC)
    settings, variant = build_settings(
        strategy_id="S01", symbol="EURUSDm", start=start, end=start + timedelta(days=1), costs=COSTS, risk_percent=1.0,
        cost_threshold=0.25, digits=5,
    )  # fmt: skip
    with pytest.raises(ValidationFailed):
        await validate(h.repos, settings=settings, variant=variant, out_dir=tmp_path, now=NOW)
    assert not (tmp_path / "ledger.jsonl").exists()  # a run that read nothing is not a look
