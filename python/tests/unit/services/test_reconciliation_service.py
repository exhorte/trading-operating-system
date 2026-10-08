"""ReconciliationService against a real database and a simulated terminal: what executed commands left at the broker, what is
unexpected, and how a command in doubt is settled — from the broker's own data, never by guessing."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.support.harness import Harness
from tests.unit.services.test_accounts_service import exness
from tests.unit.services.test_execution_service import LOGIN, FakeLink, Rig, make_rig, report, sent_command
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.events import (
    CommandReconciled,
    ExecutionReported,
    ReconciliationCompleted,
    ReconciliationMismatch,
    ReconciliationStarted,
)
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.execution.trace import command_trace
from trading_os.domain.positions.reconciliation import MismatchKind, MismatchSeverity
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.fake import (
    DEAL_ENTRY_IN,
    DEAL_ENTRY_OUT,
    DEAL_TYPE_BUY,
    DEAL_TYPE_SELL,
    FakeAccount,
    FakeMt5,
)
from trading_os.infrastructure.mt5.wire import ExecutionAck, ExecutionReconciled
from trading_os.services.reconciliation import ReconciliationService
from trading_os.shared.errors import Conflict, Unavailable

pytestmark = pytest.mark.db

MAGIC = 1001
ORDER_REFUSED = 5  # ORDER_STATE_REJECTED


@dataclass
class Env:
    rig: Rig
    recon: ReconciliationService
    terminal: FakeMt5

    @property
    def account_id(self) -> str:
        return self.rig.account.id


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def make(h: Harness) -> Env:
    rig = await make_rig(h, AutonomyMode.ARMED)
    assert isinstance(rig.link, FakeLink)
    rig.link.agent_id = f"mt5-execution-agent-{MAGIC}"
    recon = ReconciliationService(
        accounts=rig.accounts, execution=rig.execution, repos=h.repos, events=h.events, clock=h.clock
    )
    return Env(rig, recon, h.terminal(rig.account))


def place(env: Env, command_id: str, identifier: int, **overrides: object) -> None:
    """The position a filled command leaves at the broker, stamped like the agent stamps its orders."""
    fields: dict[str, object] = {
        "identifier": identifier, "symbol": "EURUSDm", "side": 0, "volume": 0.05, "price_open": 1.1, "sl": 1.099,
        "tp": 1.103, "magic": MAGIC, "comment": command_trace(command_id),
    }  # fmt: skip
    fields.update(overrides)
    env.terminal.add_position(**fields)  # type: ignore[arg-type]


async def fill(
    env: Env, command_id: str, identifier: int | None = 9001, *, placed: bool = True, **position: object
) -> None:
    """A command sent, accepted and reported FILLED — and (by default) its position at the broker."""
    await sent_command(env.rig, command_id)
    await env.rig.execution.on_ack(LOGIN, ExecutionAck(account_id=LOGIN, command_id=command_id, status="ACCEPTED"))
    await env.rig.execution.on_report(
        LOGIN,
        report(command_id, "FILLED", filled_volume=0.05, average_price=1.1, broker_retcode="10009",
               broker_order_id=identifier, broker_position_id=identifier),
    )  # fmt: skip
    if placed and identifier is not None:
        place(env, command_id, identifier, **position)


async def lose(env: Env, command_id: str) -> None:
    """A command sent whose outcome the core never learned (the ambiguous broker answer): UNKNOWN."""
    await sent_command(env.rig, command_id)
    await env.rig.execution.on_report(LOGIN, report(command_id, "FAILED", broker_retcode="10012", detail="timeout"))
    assert (await env.rig.execution.get(command_id)).state is CommandState.UNKNOWN  # type: ignore[union-attr]


async def state_of(env: Env, command_id: str) -> CommandState:
    command = await env.rig.execution.get(command_id)
    assert command is not None
    return command.state


def settle_time(h: Harness, seconds: float = 60) -> None:
    h.clock.advance(seconds=seconds)  # past the grace a fill gets to reach the position list


# ------------------------------------------------------------------------------------------------------ the healthy case


async def test_a_consistent_account_is_clean_and_confirms_the_executed_command(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-ok-1")
    settle_time(h)
    run = await env.recon.reconcile(env.account_id)
    assert run.readable and list(run.mismatches) == [] and run.positions_checked == 1 and run.confirmed == 1
    assert await state_of(env, "cmd-ok-1") is CommandState.RECONCILED  # EXECUTED → RECONCILED: the position is there
    assert [type(e) for e in h.recorder.events if isinstance(e, ReconciliationStarted | ReconciliationCompleted)] == [
        ReconciliationStarted, ReconciliationCompleted,
    ]  # fmt: skip
    assert env.recon.report(env.account_id) == run and env.recon.consecutive_failures(env.account_id) == 0
    assert env.recon.last_success_at(env.account_id) == run.finished_at

    again = await env.recon.reconcile(
        env.account_id
    )  # still watched after it is reconciled: nothing new, nothing wrong
    assert list(again.mismatches) == [] and again.confirmed == 0


async def test_a_report_without_a_position_id_is_matched_through_the_comment_trace(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-noid-1", identifier=None, placed=False)
    place(env, "cmd-noid-1", 9150)
    settle_time(h)
    run = await env.recon.reconcile(env.account_id)
    assert list(run.mismatches) == [] and run.confirmed == 1
    assert await state_of(env, "cmd-noid-1") is CommandState.RECONCILED


# ------------------------------------------------------------------------------------------------------ divergences


async def test_a_missing_position_is_critical_and_announced_once(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-gone-1", placed=False)
    settle_time(h)
    run = await env.recon.reconcile(env.account_id)
    assert [m.kind for m in run.mismatches] == [MismatchKind.MISSING_POSITION]
    assert run.critical and run.critical[0].command_id == "cmd-gone-1" and run.confirmed == 0
    assert await state_of(env, "cmd-gone-1") is CommandState.EXECUTED  # never confirmed what is not there

    h.clock.advance(seconds=5)
    again = await env.recon.reconcile(env.account_id)
    assert len(again.mismatches) == 1  # still true …
    assert len(h.recorder.of(ReconciliationMismatch)) == 1  # … but announced once


async def test_a_position_closed_by_its_stop_is_found_closed_in_the_history_not_missing(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-stop-1")
    settle_time(h)
    assert list((await env.recon.reconcile(env.account_id)).mismatches) == []
    env.terminal.remove_position(9001)
    env.terminal.add_deal(
        position_id=9001, symbol="EURUSDm", side=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, volume=0.05, price=1.099,
        server_time=int(h.clock.now().timestamp()), profit=-5.0,
    )  # fmt: skip
    h.clock.advance(seconds=5)
    run = await env.recon.reconcile(env.account_id)
    assert list(run.mismatches) == [] and run.positions_checked == 0


async def test_a_position_recorded_closed_is_not_missing(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-rec-1")
    settle_time(h)
    await env.recon.reconcile(env.account_id)
    env.terminal.remove_position(9001)
    await h.db.execute(
        "INSERT INTO closed_trades (account_id, broker_position_id, symbol, side, volume, realized_pnl, exit_price, "
        "closed_at) VALUES (%s, '9001', 'EURUSDm', 'buy', 0.05, -5, 1.099, %s)",
        (env.account_id, h.clock.now()),
    )
    assert list((await env.recon.reconcile(env.account_id)).mismatches) == []


async def test_a_stray_position_under_our_magic_is_critical_a_manual_one_only_a_warning(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-ok-2")
    env.terminal.add_position(identifier=777, symbol="EURUSDm", side=1, volume=0.02, price_open=1.1, magic=MAGIC)
    env.terminal.add_position(identifier=778, symbol="EURUSDm", side=1, volume=0.02, price_open=1.1, magic=0)
    settle_time(h)
    run = await env.recon.reconcile(env.account_id)
    by_position = {m.position_id: m for m in run.mismatches}
    assert by_position["777"].severity is MismatchSeverity.CRITICAL and not by_position["777"].external
    assert by_position["778"].severity is MismatchSeverity.WARNING and by_position["778"].external
    assert len(run.critical) == 1 and len(run.warnings) == 1


async def test_a_stop_moved_by_hand_is_a_warning_and_does_not_hide_that_the_position_exists(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-mv-1", sl=1.0995)
    settle_time(h)
    run = await env.recon.reconcile(env.account_id)
    assert [(m.kind, m.field, m.severity) for m in run.mismatches] == [
        (MismatchKind.POSITION_MISMATCH, "stop_loss", MismatchSeverity.WARNING)
    ]
    assert run.confirmed == 1 and await state_of(env, "cmd-mv-1") is CommandState.RECONCILED


async def test_a_removed_stop_is_critical_and_the_command_is_not_confirmed(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-nostop-1", sl=0.0)
    settle_time(h)
    run = await env.recon.reconcile(env.account_id)
    assert run.critical and run.critical[0].field == "stop_loss" and run.confirmed == 0
    assert await state_of(env, "cmd-nostop-1") is CommandState.EXECUTED


async def test_a_fill_whose_report_has_not_landed_is_not_unexpected(h: Harness) -> None:
    env = await make(h)
    await sent_command(env.rig, "cmd-fly-1")  # SENT; the broker already filled it, the agent's report is on its way
    place(env, "cmd-fly-1", 9100)
    run = await env.recon.reconcile(env.account_id)
    assert list(run.mismatches) == [] and await state_of(env, "cmd-fly-1") is CommandState.SENT

    await env.rig.execution.on_report(
        LOGIN, report("cmd-fly-1", "FILLED", filled_volume=0.05, average_price=1.1, broker_position_id=9100)
    )
    settle_time(h)
    landed = await env.recon.reconcile(env.account_id)
    assert list(landed.mismatches) == [] and landed.confirmed == 1


async def test_a_position_for_a_command_recorded_as_failed_is_the_worst_finding(h: Harness) -> None:
    env = await make(h)
    await sent_command(env.rig, "cmd-dead-1")
    await env.rig.execution.on_report(LOGIN, report("cmd-dead-1", "FAILED", broker_retcode="10006", detail="rejected"))
    assert await state_of(env, "cmd-dead-1") is CommandState.FAILED
    place(env, "cmd-dead-1", 9500)  # … yet the broker holds a position carrying its trace
    run = await env.recon.reconcile(env.account_id)
    assert len(run.critical) == 1 and run.critical[0].command_id == "cmd-dead-1"
    assert run.critical[0].kind is MismatchKind.UNEXPECTED_POSITION and "FAILED" in run.critical[0].detail


async def test_pending_orders_are_matched_to_their_command_or_flagged(h: Harness) -> None:
    env = await make(h)
    await sent_command(env.rig, "cmd-pend-1")
    env.terminal.add_pending_order(ticket=71, symbol="EURUSDm", magic=MAGIC, comment=command_trace("cmd-pend-1"))
    assert list((await env.recon.reconcile(env.account_id)).mismatches) == []
    env.terminal.add_pending_order(ticket=72, symbol="EURUSDm", magic=MAGIC, comment="who put me here")
    run = await env.recon.reconcile(env.account_id)
    assert [(m.kind, m.severity) for m in run.mismatches] == [(MismatchKind.ORDER_MISMATCH, MismatchSeverity.CRITICAL)]


# ------------------------------------------------------------------------------------------------------ in doubt


async def test_an_unknown_command_is_settled_from_the_position_the_broker_holds(h: Harness) -> None:
    env = await make(h)
    await lose(env, "cmd-unk-1")
    place(env, "cmd-unk-1", 9200)
    run = await env.recon.reconcile(env.account_id)
    assert run.settled == 1 and list(run.mismatches) == []
    command = await env.rig.execution.get("cmd-unk-1")
    assert command is not None and command.state is CommandState.RECONCILED
    assert (command.broker_position_id, command.filled_volume, command.average_price) == ("9200", 0.05, 1.1)
    assert "reconciled by the core" in command.detail
    settled = h.recorder.of(CommandReconciled)
    assert [(e.command_id, e.outcome, e.source) for e in settled] == [("cmd-unk-1", "executed", "core")]
    assert h.recorder.of(ExecutionReported)[-1].broker_position_id == "9200"  # the journal learns the fill
    record = (await h.repos.execution.reconciliations(env.account_id))[0]
    assert record.outcome == "executed" and record.attempts == 1


async def test_an_unknown_command_whose_position_already_closed_is_settled_from_the_deal_history(h: Harness) -> None:
    env = await make(h)
    await lose(env, "cmd-unk-2")
    now = int(h.clock.now().timestamp())
    trace = command_trace("cmd-unk-2")
    env.terminal.add_deal(position_id=9300, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, volume=0.05,
                          price=1.1, server_time=now, magic=MAGIC, comment=trace)  # fmt: skip
    env.terminal.add_deal(position_id=9300, symbol="EURUSDm", side=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, volume=0.05,
                          price=1.099, server_time=now + 20, profit=-5.0)  # fmt: skip
    run = await env.recon.reconcile(env.account_id)
    command = await env.rig.execution.get("cmd-unk-2")
    assert run.settled == 1 and command is not None and command.state is CommandState.RECONCILED
    assert command.broker_position_id == "9300" and command.average_price == 1.1
    settle_time(h)  # later runs find it closed in the history, not missing
    assert list((await env.recon.reconcile(env.account_id)).mismatches) == []


async def test_an_order_that_the_broker_refused_settles_the_command_without_a_position(h: Harness) -> None:
    env = await make(h)
    await lose(env, "cmd-unk-3")
    env.terminal.add_history_order(ticket=5000, symbol="EURUSDm", state=ORDER_REFUSED, magic=MAGIC,
                                   comment=command_trace("cmd-unk-3"))  # fmt: skip
    run = await env.recon.reconcile(env.account_id)
    command = await env.rig.execution.get("cmd-unk-3")
    assert run.settled == 1 and command is not None and command.state is CommandState.RECONCILED
    assert command.broker_position_id is None and "REJECTED" in command.detail
    assert [e.outcome for e in h.recorder.of(CommandReconciled)] == ["rejected"]
    assert h.recorder.of(ExecutionReported) == []  # nothing was executed: no fill fact
    assert list(run.mismatches) == []


async def test_not_found_never_closes_anything_and_is_retried_with_a_backoff(h: Harness) -> None:
    env = await make(h)
    await lose(env, "cmd-unk-4")
    first = await env.recon.reconcile(env.account_id)
    command = await env.rig.execution.get("cmd-unk-4")
    assert command is not None and command.state is CommandState.RECONCILING and command.attempts == 1
    assert "not found yet" in command.detail and first.settled == 0
    assert [(m.kind, m.severity) for m in first.mismatches] == [
        (MismatchKind.UNKNOWN_EXECUTION, MismatchSeverity.WARNING)
    ]
    rows = len(await h.repos.execution.transitions("cmd-unk-4"))

    await env.recon.reconcile(env.account_id)  # too soon: not searched again, no new row
    assert len(await h.repos.execution.transitions("cmd-unk-4")) == rows

    h.clock.advance(seconds=11)
    await env.recon.reconcile(env.account_id)
    again = await env.rig.execution.get("cmd-unk-4")
    assert again is not None and again.state is CommandState.RECONCILING and again.attempts == 2
    assert len(await h.repos.execution.transitions("cmd-unk-4")) == rows + 1

    h.clock.advance(minutes=5)  # an order that may be live and cannot be found for minutes is a critical matter
    late = await env.recon.reconcile(env.account_id)
    assert [m.severity for m in late.mismatches] == [MismatchSeverity.CRITICAL]
    assert await state_of(env, "cmd-unk-4") is CommandState.RECONCILING  # still never guessed at


async def test_a_command_the_agent_already_settled_is_left_alone(h: Harness) -> None:
    env = await make(h)
    await lose(env, "cmd-unk-5")
    await env.rig.execution.on_reconciled(
        LOGIN,
        ExecutionReconciled(account_id=LOGIN, command_id="cmd-unk-5", outcome="executed", symbol="EURUSDm", side="BUY",
                            broker_position_id=9400, filled_volume=0.05, average_price=1.1, attempts=1,
                            detail="found by the agent"),
    )  # fmt: skip
    assert [e.source for e in h.recorder.of(CommandReconciled)] == ["agent"]
    place(env, "cmd-unk-5", 9400)
    settle_time(h)
    run = await env.recon.reconcile(env.account_id)
    assert run.settled == 0 and list(run.mismatches) == []
    assert len(h.recorder.of(CommandReconciled)) == 1


# ------------------------------------------------------------------------------------------------------ cannot trust the read


async def test_the_wrong_account_stops_everything_else_from_being_trusted(h: Harness) -> None:
    env = await make(h)
    await lose(env, "cmd-unk-6")
    other = await env.rig.accounts.create(exness(login=7_000_007, terminal_path="C:/MT5/other"))
    env.terminal.accounts[7_000_007] = FakeAccount(login=7_000_007, server="Exness-MT5Trial", password="x")
    env.terminal.current_login = 7_000_007  # the user switched the terminal by hand
    env.terminal.add_position(identifier=1, symbol="EURUSDm", side=0, volume=0.01, price_open=1.1, magic=MAGIC,
                              comment=command_trace("cmd-unk-6"))  # fmt: skip
    run = await env.recon.reconcile(env.account_id)
    assert [(m.kind, m.severity) for m in run.mismatches] == [
        (MismatchKind.ACCOUNT_MISMATCH, MismatchSeverity.CRITICAL)
    ]
    assert other.id in run.mismatches[0].detail
    assert run.settled == 0 and await state_of(env, "cmd-unk-6") is CommandState.UNKNOWN  # not settled on foreign data


async def test_a_terminal_that_cannot_be_read_concludes_nothing(h: Harness) -> None:
    env = await make(h)
    await fill(env, "cmd-ok-3")
    settle_time(h)
    env.terminal.initialized = False
    run = await env.recon.reconcile(env.account_id)
    assert (
        not run.readable
        and list(run.mismatches) == []
        and run.error
        and env.recon.consecutive_failures(env.account_id) == 1
    )
    assert [e.readable for e in h.recorder.of(ReconciliationCompleted)] == [False]
    assert await state_of(env, "cmd-ok-3") is CommandState.EXECUTED  # nothing confirmed on an unverified read

    env.terminal.initialized = True
    healthy = await env.recon.reconcile(env.account_id)
    assert healthy.readable and env.recon.consecutive_failures(env.account_id) == 0 and healthy.confirmed == 1


async def test_a_database_that_cannot_be_read_concludes_nothing(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    env = await make(h)
    await fill(env, "cmd-ok-4")
    settle_time(h)

    async def broken(*args: object, **kwargs: object) -> list[object]:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(h.repos.execution, "created_since", broken)
    run = await env.recon.reconcile(env.account_id)
    assert not run.readable and env.recon.consecutive_failures(env.account_id) == 1
    assert "database unavailable" in (run.error or "")


async def test_reconciling_needs_a_connected_account(h: Harness) -> None:
    env = await make(h)
    await env.rig.accounts.disconnect(env.account_id)
    with pytest.raises(Conflict) as caught:
        await env.recon.reconcile(env.account_id)
    assert caught.value.code == "account_not_connected"


async def test_every_connected_account_is_reconciled_and_a_disconnected_one_is_forgotten(h: Harness) -> None:
    env = await make(h)
    reports = await env.recon.reconcile_connected()
    assert [r.account_id for r in reports] == [env.account_id]
    env.recon.forget(env.account_id)
    assert env.recon.report(env.account_id) is None and env.recon.last_success_at(env.account_id) is None
