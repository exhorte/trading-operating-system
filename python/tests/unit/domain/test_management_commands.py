"""MODIFY / CLOSE / PARTIAL_CLOSE / CANCEL and LIMIT, validated by the core before the agent sees them (ADR 0023)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from trading_os.domain.execution.commands import CommandKind, ExecutionRequest
from trading_os.domain.execution.reasons import RejectCode
from trading_os.domain.execution.validation import ValidationContext, validate
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import Side
from trading_os.infrastructure.mt5.wire import cancel_line, close_line, modify_line

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
ACCOUNT = "ACC-A"
CAPS = frozenset({"modify", "close", "cancel"})


def position(**overrides: object) -> Position:
    base: dict[str, object] = {
        "position_id": "987",
        "account_id": ACCOUNT,
        "symbol": "EURUSDm",
        "side": Side.BUY,
        "volume": 0.10,
        "entry_price": 1.1000,
        "current_price": 1.1020,
        "stop_loss": 1.0990,
        "take_profit": 1.1050,
    }
    base.update(overrides)
    return Position(**base)


def pending() -> PendingOrder:
    return PendingOrder(
        order_id="55", account_id=ACCOUNT, symbol="EURUSDm", side=Side.BUY, order_type="limit", volume=0.1, price=1.0990
    )


def ctx(**overrides: object) -> ValidationContext:
    base: dict[str, object] = {
        "now": NOW,
        "connected_account_id": ACCOUNT,
        "active_account_id": ACCOUNT,
        "agent_registered": True,
        "agent_capabilities": CAPS,
        "positions_known": True,
        "position": position(),
        "pending_order": pending(),
    }
    base.update(overrides)
    return ValidationContext(**base)


def req(kind: CommandKind, **overrides: object) -> ExecutionRequest:
    base: dict[str, object] = {
        "command_id": "pm-test-1",
        "account_id": ACCOUNT,
        "kind": kind,
        "symbol": "EURUSDm",
        "position_id": "987",
    }
    base.update(overrides)
    return ExecutionRequest(**base)


def codes(request: ExecutionRequest, context: ValidationContext) -> list[RejectCode]:
    return [r.code for r in validate(request, context)]


class TestModify:
    def test_a_tighter_stop_is_accepted_and_an_equal_one_is_harmless(self) -> None:
        assert validate(req(CommandKind.MODIFY, stop_loss=1.1000), ctx()) == []
        assert validate(req(CommandKind.MODIFY, stop_loss=1.0990), ctx()) == []

    def test_a_stop_never_moves_away_from_the_price(self) -> None:
        assert RejectCode.STOP_LOOSENED in codes(req(CommandKind.MODIFY, stop_loss=1.0980), ctx())
        short = position(side=Side.SELL, entry_price=1.1000, current_price=1.0980, stop_loss=1.1010, take_profit=1.0950)
        assert RejectCode.STOP_LOOSENED in codes(req(CommandKind.MODIFY, stop_loss=1.1020), ctx(position=short))
        assert validate(req(CommandKind.MODIFY, stop_loss=1.1005), ctx(position=short)) == []

    def test_a_stop_cannot_be_removed_and_a_modify_must_change_something(self) -> None:
        assert RejectCode.STOP_REQUIRED in codes(req(CommandKind.MODIFY, stop_loss=0.0), ctx())
        assert RejectCode.INVALID_REQUEST in codes(req(CommandKind.MODIFY), ctx())

    def test_a_stop_must_stay_behind_the_price(self) -> None:
        assert RejectCode.INVALID_REQUEST in codes(req(CommandKind.MODIFY, stop_loss=1.1020), ctx())
        assert RejectCode.INVALID_REQUEST in codes(req(CommandKind.MODIFY, stop_loss=1.1030), ctx())

    def test_a_position_without_a_stop_may_be_given_one(self) -> None:
        naked = position(stop_loss=0.0)
        assert validate(req(CommandKind.MODIFY, stop_loss=1.0985), ctx(position=naked)) == []

    def test_only_a_target_can_move_on_its_own(self) -> None:
        assert validate(req(CommandKind.MODIFY, take_profit=1.1060), ctx()) == []

    def test_the_numbers_of_the_position_are_needed_to_judge_a_stop(self) -> None:
        assert RejectCode.POSITION_NOT_FOUND in codes(
            req(CommandKind.MODIFY, stop_loss=1.1000), ctx(positions_known=False, position=None)
        )
        assert RejectCode.POSITION_NOT_FOUND in codes(req(CommandKind.MODIFY, stop_loss=1.1000), ctx(position=None))

    def test_the_symbol_must_be_the_positions(self) -> None:
        assert RejectCode.SYMBOL_MISMATCH in codes(req(CommandKind.MODIFY, symbol="XAUUSDm", stop_loss=1.1000), ctx())


class TestCloseAndPartialClose:
    def test_a_close_needs_no_decision_and_no_sizing(self) -> None:
        assert validate(req(CommandKind.CLOSE), ctx()) == []

    def test_a_position_the_core_sees_nowhere_is_not_closable(self) -> None:
        assert RejectCode.POSITION_NOT_FOUND in codes(req(CommandKind.CLOSE), ctx(position=None))

    def test_a_close_still_goes_through_when_the_core_has_no_view_yet(self) -> None:
        # reducing exposure is never blocked by blindness: the agent and the broker have the last word
        assert validate(req(CommandKind.CLOSE), ctx(positions_known=False, position=None)) == []

    def test_a_partial_close_is_strictly_inside_the_open_volume(self) -> None:
        assert validate(req(CommandKind.PARTIAL_CLOSE, volume=0.05), ctx()) == []
        assert RejectCode.VOLUME_INVALID in codes(req(CommandKind.PARTIAL_CLOSE, volume=0.10), ctx())
        assert RejectCode.VOLUME_INVALID in codes(req(CommandKind.PARTIAL_CLOSE, volume=0.50), ctx())
        assert RejectCode.INVALID_REQUEST in codes(req(CommandKind.PARTIAL_CLOSE), ctx())

    def test_a_partial_close_needs_the_position_numbers(self) -> None:
        assert RejectCode.POSITION_NOT_FOUND in codes(
            req(CommandKind.PARTIAL_CLOSE, volume=0.05), ctx(positions_known=False, position=None)
        )

    def test_both_need_a_position_id(self) -> None:
        assert RejectCode.INVALID_REQUEST in codes(req(CommandKind.CLOSE, position_id=None), ctx())


class TestCancel:
    def test_cancelling_a_pending_order(self) -> None:
        assert validate(req(CommandKind.CANCEL, position_id=None, order_id="55"), ctx()) == []

    def test_an_order_that_is_not_there_cannot_be_cancelled(self) -> None:
        cancel = req(CommandKind.CANCEL, position_id=None, order_id="55")
        assert RejectCode.ORDER_NOT_FOUND in codes(cancel, ctx(pending_order=None))
        assert validate(cancel, ctx(positions_known=False, pending_order=None)) == []
        assert RejectCode.INVALID_REQUEST in codes(req(CommandKind.CANCEL, position_id=None), ctx())


class TestCapabilities:
    def test_each_command_waits_for_the_capability_the_agent_announces(self) -> None:
        none = ctx(agent_capabilities=frozenset())
        assert RejectCode.AGENT_CAPABILITY_MISSING in codes(req(CommandKind.MODIFY, stop_loss=1.1000), none)
        assert RejectCode.AGENT_CAPABILITY_MISSING in codes(req(CommandKind.CLOSE), none)
        assert RejectCode.AGENT_CAPABILITY_MISSING in codes(req(CommandKind.PARTIAL_CLOSE, volume=0.05), none)
        assert RejectCode.AGENT_CAPABILITY_MISSING in codes(
            req(CommandKind.CANCEL, position_id=None, order_id="55"), none
        )


class TestWire:
    def decode(self, line: bytes) -> dict[str, object]:
        assert line.endswith(b"\n") and not line.startswith(b"\xef\xbb\xbf")
        return json.loads(line)

    def test_modify_close_and_cancel_lines(self) -> None:
        common = {
            "login": "486046157",
            "command_id": "pm-1",
            "expires_at_ms": 2_000,
            "now_ms": 1_000,
            "symbol": "EURUSDm",
        }
        modify = self.decode(modify_line(**common, position_id="987", stop_loss=1.1000, take_profit=None))
        assert modify["type"] == "execution.modify" and modify["id"] == "pm-1" and modify["positionId"] == "987"
        assert modify["sl"] == 1.1 and modify["tp"] is None and modify["accountId"] == "486046157"
        close = self.decode(close_line(**common, position_id="987", volume=0.05))
        assert close["type"] == "execution.close" and close["volume"] == 0.05 and close["expiresAt"] == 2_000
        full = self.decode(close_line(**common, position_id="987"))
        assert full["volume"] is None
        cancel = self.decode(cancel_line(**common, order_id="55"))
        assert cancel["type"] == "execution.cancel" and cancel["orderId"] == "55"
