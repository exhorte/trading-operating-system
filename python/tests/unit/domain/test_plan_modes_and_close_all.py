"""The plan's ladder read on the repository's (ADR 0034), and the rules that read a close-all batch. Pure functions: no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from tests.support.builders import make_command
from trading_os.domain.accounts.models import Environment
from trading_os.domain.autonomy.plan_modes import PlanMode, ladder, plan_mode, rights
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.close_all import (
    VERIFY_GRACE,
    CloseAllDisposition,
    CloseAllItemStatus,
    CloseAllReport,
    CloseAllStatus,
    PlannedItem,
    assess,
    batch_prefix,
    classify,
    mask_login,
    order_command_id,
    position_command_id,
)
from trading_os.domain.execution.commands import CommandState, ExecutionCommand
from trading_os.domain.primitives import Side

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
M, E = AutonomyMode, Environment


class TestThePlansLadder:
    @pytest.mark.parametrize(
        ("mode", "environment", "expected"),
        [
            (M.OFF, E.DEMO, PlanMode.OFF),
            (M.OBSERVE, E.LIVE, PlanMode.OBSERVE),
            (M.PAPER, E.LIVE, PlanMode.PAPER),
            (M.CONFIRM, E.DEMO, PlanMode.CONFIRM),
            (M.CONFIRM, E.SIMULATED, PlanMode.CONFIRM),
            (M.CONFIRM, E.LIVE, PlanMode.LIVE_CONFIRM),
            (M.ARMED, E.DEMO, PlanMode.DEMO_AUTO),
            (M.AUTONOMOUS, E.DEMO, PlanMode.DEMO_AUTO),
            (M.ARMED, E.LIVE, PlanMode.LIVE_AUTO),
            (M.AUTONOMOUS, E.LIVE, PlanMode.LIVE_AUTO),
            (M.HALTED, E.LIVE, PlanMode.HALTED),
        ],
    )
    def test_each_state_of_the_repository_has_one_name_in_the_plan(
        self, mode: AutonomyMode, environment: Environment, expected: PlanMode
    ) -> None:
        assert plan_mode(mode, environment) is expected

    def test_every_state_has_a_name_in_every_environment(self) -> None:
        for mode in AutonomyMode:
            for environment in Environment:
                assert isinstance(plan_mode(mode, environment), PlanMode)

    def test_the_rights_of_each_mode(self) -> None:
        assert not rights(PlanMode.OBSERVE).sends_orders and not rights(PlanMode.PAPER).sends_orders
        confirm = rights(PlanMode.CONFIRM)
        assert confirm.sends_orders and confirm.needs_human_confirmation and not confirm.real_money
        live_confirm = rights(PlanMode.LIVE_CONFIRM)
        assert live_confirm.sends_orders and live_confirm.needs_human_confirmation and live_confirm.real_money
        demo_auto = rights(PlanMode.DEMO_AUTO)
        assert demo_auto.sends_orders and demo_auto.needs_green_readiness and not demo_auto.real_money
        live_auto = rights(PlanMode.LIVE_AUTO)
        assert live_auto.needs_green_readiness and live_auto.real_money and not live_auto.needs_human_confirmation
        assert not rights(PlanMode.HALTED).sends_orders and not rights(PlanMode.OFF).sends_orders

    def test_the_ladder_drawn_for_an_account_follows_its_environment(self) -> None:
        assert [r.mode for r in ladder(Environment.DEMO)] == [
            PlanMode.OBSERVE,
            PlanMode.PAPER,
            PlanMode.CONFIRM,
            PlanMode.DEMO_AUTO,
        ]
        assert [r.mode for r in ladder(Environment.LIVE)][2:] == [PlanMode.LIVE_CONFIRM, PlanMode.LIVE_AUTO]


class TestTheIdsOfABatch:
    def test_the_ids_are_deterministic_and_fit_a_command_id(self) -> None:
        assert position_command_id("abc123def456", "4660123") == "ca-abc123def456-4660123"
        assert order_command_id("abc123def456", "99") == "ca-abc123def456-o99"
        assert position_command_id("abc123def456", "4660123").startswith(batch_prefix("abc123def456"))
        assert len(position_command_id("a" * 24, "9" * 20)) <= 64

    def test_the_number_is_shown_by_its_last_four_digits(self) -> None:
        assert mask_login(486046157) == "****6157" and mask_login(12) == "****"


def planned(disposition: CloseAllDisposition = CloseAllDisposition.SENT, target_id: str = "101") -> PlannedItem:
    return PlannedItem(
        target="position",
        target_id=target_id,
        symbol="EURUSDm",
        side=Side.BUY,
        volume=0.1,
        disposition=disposition,
        command_id=position_command_id("batch000001", target_id) if disposition is CloseAllDisposition.SENT else None,
    )


def command(state: CommandState, **changes: Any) -> ExecutionCommand:
    base = make_command("ca-batch000001-101", account_id="A", state=state)
    return base.model_copy(update={"completed_at": NOW, **changes})


class TestReadingAnItem:
    @pytest.mark.parametrize("state", [CommandState.PENDING, CommandState.SENT, CommandState.ACKNOWLEDGED])
    def test_a_command_on_its_way_is_in_progress(self, state: CommandState) -> None:
        assert classify(planned(), command(state), still_open=True, now=NOW).status is CloseAllItemStatus.IN_PROGRESS

    @pytest.mark.parametrize("state", [CommandState.EXECUTED, CommandState.RECONCILED])
    def test_done_is_confirmed_only_when_the_broker_no_longer_shows_it(self, state: CommandState) -> None:
        assert classify(planned(), command(state), still_open=False, now=NOW).status is CloseAllItemStatus.CONFIRMED
        assert classify(planned(), command(state), still_open=True, now=NOW).status is CloseAllItemStatus.VERIFYING

    def test_done_but_still_open_past_the_grace_is_a_mismatch(self) -> None:
        late = NOW + VERIFY_GRACE + timedelta(seconds=1)
        item = classify(planned(), command(CommandState.EXECUTED), still_open=True, now=late)
        assert item.status is CloseAllItemStatus.MISMATCH

    @pytest.mark.parametrize("state", [CommandState.UNKNOWN, CommandState.RECONCILING])
    def test_a_doubt_stays_a_doubt_even_when_the_position_is_gone(self, state: CommandState) -> None:
        assert classify(planned(), command(state), still_open=True, now=NOW).status is CloseAllItemStatus.UNKNOWN
        assert classify(planned(), command(state), still_open=False, now=NOW).status is CloseAllItemStatus.UNKNOWN

    def test_a_simulation_never_counts_as_a_closing(self) -> None:
        item = classify(planned(), command(CommandState.SIMULATED), still_open=True, now=NOW)
        assert item.status is CloseAllItemStatus.SIMULATED

    @pytest.mark.parametrize("state", [CommandState.REJECTED, CommandState.FAILED, CommandState.EXPIRED])
    def test_a_refusal_keeps_its_code(self, state: CommandState) -> None:
        item = classify(planned(), command(state, reject_code="TARGET_NOT_OURS"), still_open=True, now=NOW)
        assert item.status is CloseAllItemStatus.REJECTED and item.reject_code == "TARGET_NOT_OURS"

    def test_a_position_not_found_that_is_indeed_gone_is_already_closed(self) -> None:
        refused = command(CommandState.REJECTED, reject_code="POSITION_NOT_FOUND")
        assert classify(planned(), refused, still_open=False, now=NOW).status is CloseAllItemStatus.ALREADY_CLOSED

    def test_no_command_is_not_closable_or_already_closed_by_what_was_decided(self) -> None:
        assert (
            classify(planned(CloseAllDisposition.NOT_CLOSABLE), None, still_open=True, now=NOW).status
            is CloseAllItemStatus.NOT_CLOSABLE
        )
        assert (
            classify(planned(CloseAllDisposition.NOT_CLOSABLE), None, still_open=False, now=NOW).status
            is CloseAllItemStatus.ALREADY_CLOSED
        )
        assert (
            classify(planned(CloseAllDisposition.ALREADY_CLOSED), None, still_open=False, now=NOW).status
            is CloseAllItemStatus.ALREADY_CLOSED
        )
        assert (
            classify(planned(CloseAllDisposition.REFUSED), None, still_open=True, now=NOW).status
            is CloseAllItemStatus.REJECTED
        )
        assert (
            classify(planned(), None, still_open=True, now=NOW).status is CloseAllItemStatus.UNKNOWN
        )  # sent, but not on record


def report(
    statuses: list[tuple[CommandState | None, bool]], *, reconciled: bool = True, fresh: bool = True
) -> CloseAllReport:
    items = [
        classify(planned(target_id=str(100 + i)), command(state) if state else None, still_open=is_open, now=NOW)
        for i, (state, is_open) in enumerate(statuses)
    ]
    return assess(
        batch_id="batch000001",
        account_id="A",
        items=items,
        include_pending_orders=False,
        started_at=NOW,
        now=NOW,
        reconciled=reconciled,
        reconciliation_critical=0,
        snapshot_fresh=fresh,
        positions_open=0,
        orders_pending=0,
        other_open_positions=[],
    )


class TestReadingTheBatch:
    def test_nothing_to_close(self) -> None:
        assert report([]).status is CloseAllStatus.NOTHING_TO_CLOSE

    def test_complete_needs_every_item_confirmed_and_a_reconciliation_and_a_fresh_picture(self) -> None:
        done = [(CommandState.EXECUTED, False), (CommandState.RECONCILED, False)]
        assert report(done).status is CloseAllStatus.COMPLETE
        assert report(done, reconciled=False).status is CloseAllStatus.AWAITING_RECONCILIATION
        assert report(done, fresh=False).status is CloseAllStatus.AWAITING_RECONCILIATION

    def test_one_item_still_moving_keeps_the_whole_in_progress(self) -> None:
        batch = report([(CommandState.EXECUTED, False), (CommandState.SENT, True)])
        assert batch.status is CloseAllStatus.IN_PROGRESS and not batch.final and batch.counts.in_progress == 1

    def test_one_problem_makes_it_incomplete_whatever_else_succeeded(self) -> None:
        batch = report([(CommandState.EXECUTED, False), (CommandState.REJECTED, True)])
        assert batch.status is CloseAllStatus.INCOMPLETE and batch.final and batch.counts.rejected == 1
        assert not batch.simulated_only

    def test_a_batch_of_simulations_is_flagged_as_having_closed_nothing(self) -> None:
        batch = report([(CommandState.SIMULATED, True), (CommandState.SIMULATED, True)])
        assert batch.status is CloseAllStatus.INCOMPLETE and batch.simulated_only and batch.counts.confirmed == 0
