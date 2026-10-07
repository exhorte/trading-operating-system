"""Reconciliation (missing position, unexpected position, wrong volume, wrong SL, wrong TP …) and supervision policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.positions.reconciliation import (
    ExpectedOrder,
    ExpectedPosition,
    Mismatch,
    MismatchKind,
    MismatchSeverity,
    ReconciliationInput,
    UnresolvedCommand,
    reconcile,
)
from trading_os.domain.primitives import Side
from trading_os.domain.system.supervision import Action, Finding, Severity, actions_for, is_stale, worst

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
ACCOUNT = "TEST-ACC-1"
MAGIC = 1001


def expected(**overrides: object) -> ExpectedPosition:
    base: dict[str, object] = {
        "command_id": "cmd-1",
        "account_id": ACCOUNT,
        "symbol": "EURUSDm",
        "side": Side.BUY,
        "volume": 0.09,
        "stop_loss": 1.0990,
        "take_profit": 1.1030,
        "broker_position_id": "555",
        "executed_at": NOW - timedelta(minutes=5),
    }
    base.update(overrides)
    return ExpectedPosition(**base)


def actual(**overrides: object) -> Position:
    base: dict[str, object] = {
        "position_id": "555",
        "account_id": ACCOUNT,
        "symbol": "EURUSDm",
        "side": Side.BUY,
        "volume": 0.09,
        "entry_price": 1.1,
        "stop_loss": 1.0990,
        "take_profit": 1.1030,
        "magic_number": MAGIC,
    }
    base.update(overrides)
    return Position(**base)


def run(**overrides: object) -> list[Mismatch]:
    base: dict[str, object] = {
        "account_id": ACCOUNT,
        "now": NOW,
        "connected_account_id": ACCOUNT,
        "expected": [expected()],
        "actual": [actual()],
        "our_magic": MAGIC,
    }
    base.update(overrides)
    return reconcile(ReconciliationInput(**base))


def kinds(found: list[Mismatch]) -> list[MismatchKind]:
    return [m.kind for m in found]


class TestReconciliation:
    def test_a_consistent_state_has_no_findings(self) -> None:
        assert run() == []

    def test_missing_position(self) -> None:
        found = run(actual=[])
        assert kinds(found) == [MismatchKind.MISSING_POSITION]
        assert found[0].severity is MismatchSeverity.CRITICAL and found[0].command_id == "cmd-1"

    def test_a_position_closed_by_its_stop_is_not_missing(self) -> None:
        assert run(actual=[], closed_position_ids=frozenset({"555"})) == []

    def test_a_fresh_fill_gets_a_grace_period(self) -> None:
        assert run(actual=[], expected=[expected(executed_at=NOW - timedelta(seconds=5))]) == []

    def test_unexpected_position_under_our_magic_is_critical(self) -> None:
        stray = actual(position_id="999")
        found = run(actual=[actual(), stray])
        assert kinds(found) == [MismatchKind.UNEXPECTED_POSITION]
        assert (
            found[0].severity is MismatchSeverity.CRITICAL and not found[0].external and found[0].position_id == "999"
        )

    def test_a_position_opened_by_hand_is_only_a_warning(self) -> None:
        manual = actual(position_id="777", magic_number=0)
        found = run(actual=[actual(), manual])
        assert kinds(found) == [MismatchKind.UNEXPECTED_POSITION]
        assert found[0].severity is MismatchSeverity.WARNING and found[0].external

    def test_wrong_volume(self) -> None:
        found = run(actual=[actual(volume=0.05)])
        assert kinds(found) == [MismatchKind.POSITION_MISMATCH]
        assert (found[0].field, found[0].expected, found[0].actual) == ("volume", "0.09", "0.05")

    def test_wrong_stop_loss(self) -> None:
        found = run(actual=[actual(stop_loss=1.0980)])
        assert kinds(found) == [MismatchKind.POSITION_MISMATCH] and found[0].field == "stop_loss"
        assert found[0].severity is MismatchSeverity.WARNING

    def test_a_removed_stop_is_critical(self) -> None:
        found = run(actual=[actual(stop_loss=0.0)])
        assert found[0].field == "stop_loss" and found[0].severity is MismatchSeverity.CRITICAL

    def test_wrong_take_profit(self) -> None:
        found = run(actual=[actual(take_profit=1.1050)])
        assert kinds(found) == [MismatchKind.POSITION_MISMATCH] and found[0].field == "take_profit"

    def test_symbol_mismatch(self) -> None:
        found = run(actual=[actual(symbol="GBPUSDm")])
        assert MismatchKind.SYMBOL_MISMATCH in kinds(found)
        assert next(m for m in found if m.kind is MismatchKind.SYMBOL_MISMATCH).severity is MismatchSeverity.CRITICAL

    def test_opposite_side_is_critical(self) -> None:
        found = run(actual=[actual(side=Side.SELL)])
        assert found[0].field == "side" and found[0].severity is MismatchSeverity.CRITICAL

    def test_account_mismatch_stops_everything_else_from_being_trusted(self) -> None:
        found = run(connected_account_id="OTHER", actual=[])
        assert kinds(found) == [MismatchKind.ACCOUNT_MISMATCH] and found[0].severity is MismatchSeverity.CRITICAL
        assert run(connected_account_id=None)[0].kind is MismatchKind.ACCOUNT_MISMATCH

    def test_the_agent_scan_links_a_position_to_its_command_when_the_report_had_no_id(self) -> None:
        loose = expected(broker_position_id=None)
        assert run(expected=[loose], command_by_position={"555": "cmd-1"}) == []

    def test_unknown_execution_escalates_with_time(self) -> None:
        young = UnresolvedCommand(command_id="cmd-2", state=CommandState.UNKNOWN, since=NOW - timedelta(seconds=30))
        old = UnresolvedCommand(command_id="cmd-3", state=CommandState.RECONCILING, since=NOW - timedelta(minutes=5))
        found = run(unresolved=[young, old])
        assert [m.severity for m in found] == [MismatchSeverity.WARNING, MismatchSeverity.CRITICAL]
        assert kinds(found) == [MismatchKind.UNKNOWN_EXECUTION] * 2

    def test_orders(self) -> None:
        pending = PendingOrder(
            order_id="900",
            account_id=ACCOUNT,
            symbol="EURUSDm",
            side=Side.BUY,
            order_type="limit",
            volume=0.1,
            price=1.09,
            magic_number=MAGIC,
            comment="stray",
        )
        found = run(actual_orders=[pending])
        assert kinds(found) == [MismatchKind.ORDER_MISMATCH] and found[0].severity is MismatchSeverity.CRITICAL
        missing = run(
            expected_orders=[ExpectedOrder(command_id="cmd-9", symbol="EURUSDm", side=Side.BUY, volume=0.1, price=1.09)]
        )
        assert kinds(missing) == [MismatchKind.ORDER_MISMATCH] and missing[0].severity is MismatchSeverity.WARNING


def finding(code: str, severity: Severity, persisting: bool = False) -> Finding:
    return Finding(code=code, component="x", severity=severity, detail="d", observed_at=NOW, persisting=persisting)


class TestSupervisionPolicy:
    def test_ok_needs_nothing(self) -> None:
        assert actions_for(finding("anything", Severity.OK), AutonomyMode.AUTONOMOUS) == []

    def test_stale_data_makes_the_system_safe(self) -> None:
        assert actions_for(finding("stale_market_data", Severity.MEDIUM), AutonomyMode.AUTONOMOUS) == [Action.SAFE]

    def test_mt5_disconnected_reconnects_and_is_safe_then_disarms_if_it_persists(self) -> None:
        f = finding("mt5_disconnected", Severity.HIGH)
        assert actions_for(f, AutonomyMode.OBSERVE) == [Action.RECONNECT, Action.SAFE]
        assert actions_for(f.model_copy(update={"persisting": True}), AutonomyMode.AUTONOMOUS) == [
            Action.RECONNECT,
            Action.SAFE,
            Action.DISARM,
        ]

    def test_a_stale_agent_heartbeat_disarms_only_automatic_modes(self) -> None:
        f = finding("agent_heartbeat_stale", Severity.HIGH)
        assert actions_for(f, AutonomyMode.CONFIRM) == [Action.SAFE]
        assert actions_for(f, AutonomyMode.ARMED) == [Action.SAFE, Action.DISARM]

    def test_database_down_halts_autonomous_trading(self) -> None:
        f = finding("database_unavailable", Severity.HIGH)
        assert actions_for(f, AutonomyMode.OBSERVE) == [Action.SAFE]
        assert actions_for(f, AutonomyMode.AUTONOMOUS) == [Action.SAFE, Action.HALT]

    def test_execution_failure_and_unknown_commands_reconcile(self) -> None:
        for code in ("execution_failure", "unknown_command"):
            assert actions_for(finding(code, Severity.HIGH), AutonomyMode.CONFIRM) == [Action.SAFE, Action.RECONCILE]

    def test_a_persistent_reconciliation_failure_halts(self) -> None:
        f = finding("reconciliation_failed", Severity.HIGH)
        assert actions_for(f, AutonomyMode.OBSERVE) == [Action.RECONCILE]
        assert actions_for(f.model_copy(update={"persisting": True}), AutonomyMode.OBSERVE) == [
            Action.RECONCILE,
            Action.HALT,
        ]

    def test_critical_findings_always_halt(self) -> None:
        for code in ("unexpected_position", "critical_error", "never_heard_of_this"):
            assert Action.HALT in actions_for(finding(code, Severity.CRITICAL), AutonomyMode.OFF)

    def test_unknown_codes_fall_back_to_severity(self) -> None:
        assert actions_for(finding("novel", Severity.MEDIUM), AutonomyMode.CONFIRM) == [Action.SAFE]
        assert actions_for(finding("novel", Severity.HIGH), AutonomyMode.AUTONOMOUS) == [Action.SAFE, Action.DISARM]

    def test_worst_and_staleness(self) -> None:
        assert worst([]) is Severity.OK
        assert (
            worst([finding("a", Severity.MEDIUM), finding("b", Severity.CRITICAL), finding("c", Severity.HIGH)])
            is Severity.CRITICAL
        )
        assert is_stale(None, NOW, 30) and is_stale(NOW - timedelta(seconds=31), NOW, 30)
        assert not is_stale(NOW - timedelta(seconds=30), NOW, 30)
