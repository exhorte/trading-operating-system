"""PromotionService: the facts come from what the core recorded (ADR 0027)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.support.core import Core, make_ready_core
from tests.support.harness import Harness
from tests.unit.domain.validation.test_bench import COSTS, scenario_set, window
from trading_os.cli.validate import build_settings, write_outputs
from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.domain.execution.commands import CommandKind, CommandState, ExecutionCommand, ExecutionRequest
from trading_os.domain.execution.idempotency import request_fingerprint
from trading_os.domain.primitives import Side
from trading_os.domain.validation.report import run_validation
from trading_os.infrastructure.database.pool import Database

pytestmark = pytest.mark.db


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def command(core: Core, name: str, *, route: ExecutionRoute, state: CommandState, mode: AutonomyMode) -> None:
    assert core.account is not None
    request = ExecutionRequest(
        command_id=name, account_id=core.account.id, kind=CommandKind.OPEN, symbol="EURUSDm", side=Side.BUY, volume=0.1,
        stop_loss=1.099, risk_decision_id="risk-1", strategy_id="S01",
    )  # fmt: skip
    now = core.h.clock.now()
    stored = ExecutionCommand(
        request=request, fingerprint=request_fingerprint(request), state=state, route=route, mode=mode, created_at=now,
        expires_at=now,
    )  # fmt: skip
    assert await core.h.repos.execution.insert(stored, now)


async def test_the_report_counts_what_the_core_recorded(h: Harness, tmp_path: Path) -> None:
    core = await make_ready_core(h, top=AutonomyMode.PAPER)
    core.c.promotion._validation_dir = tmp_path  # type: ignore[misc]
    for i in range(3):
        await command(
            core, f"cmd-paper-{i}", route=ExecutionRoute.PAPER, state=CommandState.SIMULATED, mode=AutonomyMode.PAPER
        )
    await command(
        core, "cmd-real-1", route=ExecutionRoute.CONFIRM, state=CommandState.RECONCILED, mode=AutonomyMode.CONFIRM
    )
    await command(
        core, "cmd-doubt-1", route=ExecutionRoute.AUTOMATIC, state=CommandState.UNKNOWN, mode=AutonomyMode.ARMED
    )
    report = await core.c.promotion.report(core.account.id)  # type: ignore[union-attr]
    assert report.advisory and report.mode is AutonomyMode.PAPER and report.account_id == core.account.id  # type: ignore[union-attr]
    confirm = next(s for s in report.steps if s.to_mode is AutonomyMode.CONFIRM)
    evidence = {c.criterion_id: c.evidence for c in confirm.criteria}
    assert evidence["paper_commands"].startswith("3 order(s)") and evidence["no_doubt"].startswith("1 command")
    assert confirm.current and not confirm.met
    armed = next(s for s in report.steps if s.to_mode is AutonomyMode.ARMED)
    assert {c.criterion_id: c.evidence for c in armed.criteria}["confirmed_orders"].startswith("1 order(s)")


async def test_limits_written_by_the_user_are_read_from_the_account(h: Harness, tmp_path: Path) -> None:
    core = await make_ready_core(h, top=AutonomyMode.OBSERVE)  # add_account(configured=True)
    core.c.promotion._validation_dir = tmp_path  # type: ignore[misc]
    report = await core.c.promotion.report(core.account.id)  # type: ignore[union-attr]
    first = report.steps[0]
    assert next(c for c in first.criteria if c.criterion_id == "limits_configured").status == "met"


async def test_the_newest_validation_report_on_disk_is_the_evidence(h: Harness, tmp_path: Path) -> None:
    core = await make_ready_core(h, top=AutonomyMode.CONFIRM)
    core.c.promotion._validation_dir = tmp_path  # type: ignore[misc]
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
    write_outputs(run_validation(scenario_set(), settings, variant, now=datetime(2026, 11, 3, tzinfo=UTC)), tmp_path)
    report = await core.c.promotion.report(core.account.id)  # type: ignore[union-attr]
    armed = next(s for s in report.steps if s.to_mode is AutonomyMode.ARMED)
    by_id = {c.criterion_id: c for c in armed.criteria}
    assert by_id["validation_trades"].status == "not_met"  # the report is found: zero trades of the 100 needed
    assert (
        by_id["validation_breach"].status == "not_measured"
    )  # no trade filled, so no Monte Carlo: unmeasured is never met


async def test_a_broken_report_file_is_skipped_not_fatal(h: Harness, tmp_path: Path) -> None:
    core = await make_ready_core(h, top=AutonomyMode.OBSERVE)
    core.c.promotion._validation_dir = tmp_path  # type: ignore[misc]
    (tmp_path / "validation-S01-EURUSDm-x.json").write_text("{not json", encoding="utf-8")
    report = await core.c.promotion.report(core.account.id)  # type: ignore[union-attr]
    armed = next(s for s in report.steps if s.to_mode is AutonomyMode.ARMED)
    assert next(c for c in armed.criteria if c.criterion_id == "validation_trades").status == "not_measured"


async def test_without_an_account_nothing_is_measured(h: Harness, tmp_path: Path) -> None:
    core = await make_ready_core(h, top=AutonomyMode.OBSERVE)
    core.c.promotion._validation_dir = tmp_path  # type: ignore[misc]
    report = await core.c.promotion.report(None)
    assert report.account_id is None and not any(s.met for s in report.steps)
