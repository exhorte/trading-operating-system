"""Execution domain: lifecycle table, idempotency, broker return codes, validation (duplicate, expired, unknown, failed,
account mismatch, symbol mismatch — the mandatory cases of the mission)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.domain.execution.commands import (
    CommandKind,
    CommandState,
    ExecutionCommand,
    ExecutionRequest,
)
from trading_os.domain.execution.idempotency import ReplayOutcome, check_replay, request_fingerprint
from trading_os.domain.execution.reasons import RejectCode
from trading_os.domain.execution.retcodes import (
    RetcodeClass,
    classify_failed_report,
    classify_retcode,
    parse_retcode,
)
from trading_os.domain.execution.state import (
    IN_DOUBT_STATES,
    TERMINAL_STATES,
    CommandEvent,
    is_terminal,
    next_state,
)
from trading_os.domain.execution.validation import ValidationContext, validate
from trading_os.domain.primitives import Side
from trading_os.domain.risk.decision import RiskDecision
from trading_os.shared.errors import IllegalTransition

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
S, E = CommandState, CommandEvent
ACCOUNT = "TEST-ACC-1"


class TestLifecycle:
    def walk(self, state: CommandState, *events: CommandEvent) -> CommandState:
        for event in events:
            state = next_state(state, event)
        return state

    def test_happy_path_to_reconciled(self) -> None:
        end = self.walk(S.PENDING, E.SENT, E.ACK_ACCEPTED, E.REPORT_EXECUTED, E.POSITION_CONFIRMED)
        assert end is S.RECONCILED and is_terminal(end)

    def test_every_step_is_the_documented_one(self) -> None:
        assert next_state(S.PENDING, E.SENT) is S.SENT
        assert next_state(S.SENT, E.ACK_ACCEPTED) is S.ACKNOWLEDGED
        assert next_state(S.ACKNOWLEDGED, E.REPORT_EXECUTED) is S.EXECUTED

    def test_refusals_and_expiry(self) -> None:
        assert next_state(S.SENT, E.ACK_REJECTED) is S.REJECTED
        assert next_state(S.SENT, E.ACK_EXPIRED) is S.EXPIRED
        assert next_state(S.PENDING, E.SEND_FAILED) is S.FAILED
        assert next_state(S.PENDING, E.EXPIRED) is S.EXPIRED
        assert next_state(S.PENDING, E.CANCEL_REQUESTED) is S.CANCELLED
        assert next_state(S.ACKNOWLEDGED, E.REPORT_FAILED) is S.FAILED

    def test_a_simulated_outcome_is_its_own_terminal_never_an_execution(self) -> None:
        assert next_state(S.ACKNOWLEDGED, E.REPORT_SIMULATED) is S.SIMULATED
        assert next_state(S.SENT, E.REPORT_SIMULATED) is S.SIMULATED
        assert is_terminal(S.SIMULATED)

    def test_a_replayed_final_report_can_overtake_a_lost_ack(self) -> None:
        assert next_state(S.SENT, E.REPORT_EXECUTED) is S.EXECUTED
        assert next_state(S.SENT, E.REPORT_FAILED) is S.FAILED

    # --- UNKNOWN is first-class, never replayed, and has exactly one way out
    def test_losing_the_link_after_the_send_leaves_the_command_unknown(self) -> None:
        assert next_state(S.SENT, E.LINK_LOST) is S.UNKNOWN
        assert next_state(S.ACKNOWLEDGED, E.LINK_LOST) is S.UNKNOWN

    def test_unknown_resolves_only_through_reconciliation(self) -> None:
        assert self.walk(S.UNKNOWN, E.RECONCILIATION_STARTED, E.RECONCILIATION_PENDING, E.RECONCILED) is S.RECONCILED

    def test_unknown_never_re_enters_the_happy_path(self) -> None:
        for event in (
            E.SENT,
            E.ACK_ACCEPTED,
            E.REPORT_EXECUTED,
            E.REPORT_FAILED,
            E.EXPIRED,
            E.CANCEL_REQUESTED,
            E.SEND_FAILED,
        ):
            with pytest.raises(IllegalTransition):
                next_state(S.UNKNOWN, event)
            with pytest.raises(IllegalTransition):
                next_state(S.RECONCILING, event)

    def test_an_acknowledged_order_can_no_longer_be_cancelled_or_expired(self) -> None:
        # Once the agent has it, an order may already be live at the broker.
        for event in (E.CANCEL_REQUESTED, E.EXPIRED, E.SEND_FAILED):
            with pytest.raises(IllegalTransition):
                next_state(S.ACKNOWLEDGED, event)

    def test_terminal_states_have_no_exit(self) -> None:
        assert {S.RECONCILED, S.FAILED, S.REJECTED, S.EXPIRED, S.CANCELLED, S.SIMULATED} == set(TERMINAL_STATES)
        for state in TERMINAL_STATES:
            for event in CommandEvent:
                with pytest.raises(IllegalTransition):
                    next_state(state, event)

    def test_in_doubt_states_are_the_ones_a_restart_must_never_replay(self) -> None:
        assert {S.SENT, S.ACKNOWLEDGED, S.UNKNOWN, S.RECONCILING} == set(IN_DOUBT_STATES)

    def test_an_executed_command_whose_position_disappears_goes_to_reconciliation(self) -> None:
        assert next_state(S.EXECUTED, E.RECONCILIATION_STARTED) is S.RECONCILING

    def test_all_eight_states_of_the_mission_exist(self) -> None:
        names = {s.value for s in CommandState}
        assert {
            "PENDING",
            "SENT",
            "ACKNOWLEDGED",
            "EXECUTED",
            "FAILED",
            "UNKNOWN",
            "RECONCILING",
            "RECONCILED",
        } <= names


def request(**overrides: object) -> ExecutionRequest:
    base: dict[str, object] = {
        "command_id": "cmd-0001",
        "account_id": ACCOUNT,
        "kind": CommandKind.OPEN,
        "symbol": "EURUSDm",
        "side": Side.BUY,
        "volume": 0.09,
        "stop_loss": 1.0990,
        "take_profit": 1.1030,
        "strategy_id": "S01",
        "strategy_version": "1",
        "risk_decision_id": "risk-1",
        "expires_at": NOW + timedelta(seconds=60),
    }
    base.update(overrides)
    return ExecutionRequest(**base)


def command_for(req: ExecutionRequest) -> ExecutionCommand:
    return ExecutionCommand(
        request=req,
        fingerprint=request_fingerprint(req),
        state=CommandState.PENDING,
        route=ExecutionRoute.CONFIRM,
        mode=AutonomyMode.CONFIRM,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=60),
    )


class TestIdempotency:
    def test_a_new_id_is_new(self) -> None:
        assert check_replay(None, request()).outcome is ReplayOutcome.NEW

    def test_the_same_id_and_content_replays_the_recorded_command(self) -> None:
        stored = command_for(request())
        decision = check_replay(stored, request())
        assert decision.outcome is ReplayOutcome.REPLAY and decision.existing is stored

    def test_a_replay_a_minute_later_is_still_the_same_order(self) -> None:
        stored = command_for(request())
        later = request(expires_at=NOW + timedelta(minutes=5))
        assert check_replay(stored, later).outcome is ReplayOutcome.REPLAY

    def test_the_same_id_with_different_content_is_a_conflict(self) -> None:
        stored = command_for(request())
        for change in (
            {"volume": 1.0},
            {"symbol": "GBPUSDm"},
            {"side": Side.SELL},
            {"stop_loss": 1.0980},
            {"account_id": "OTHER"},
        ):
            assert check_replay(stored, request(**change)).outcome is ReplayOutcome.CONFLICT, change

    def test_the_fingerprint_is_stable_and_ignores_timestamps(self) -> None:
        assert request_fingerprint(request()) == request_fingerprint(request(expires_at=None))
        assert len(request_fingerprint(request())) == 64


class TestBrokerReturnCodes:
    def test_success(self) -> None:
        for code in ("10009", 10010, "TRADE_RETCODE_DONE", "10008"):
            assert classify_retcode(code) is RetcodeClass.SUCCESS, code

    def test_timeout_processing_error_and_lost_connection_are_ambiguous_never_failed(self) -> None:
        # Audit F03: the previous agent recorded these as FAILED while the order may be live.
        for code in ("10011", "10012", "10031", "TRADE_RETCODE_TIMEOUT", 10031):
            assert classify_retcode(code) is RetcodeClass.AMBIGUOUS, code

    def test_everything_else_is_a_definite_refusal(self) -> None:
        for code in ("10006", "10013", "10014", "10016", "10018", "10019", "10027", "10030"):
            assert classify_retcode(code) is RetcodeClass.FAILURE, code

    def test_no_code_at_all_is_ambiguous_we_do_not_assume_a_refusal(self) -> None:
        assert classify_retcode(None) is RetcodeClass.AMBIGUOUS
        assert classify_retcode("garbage") is RetcodeClass.AMBIGUOUS

    def test_a_refusal_before_any_broker_call_is_definite_even_without_a_code(self) -> None:
        detail = "STORE_UNWRITABLE: the UNKNOWN line could not be written — order NOT sent"
        assert classify_failed_report(None, detail) is RetcodeClass.FAILURE
        assert classify_failed_report(None, "OrderSend refused") is RetcodeClass.AMBIGUOUS
        assert classify_failed_report("10013", "OrderSend refused: retcode 10013") is RetcodeClass.FAILURE

    def test_parse(self) -> None:
        assert parse_retcode("10009") == 10009 and parse_retcode(10009) == 10009 and parse_retcode(" 10012 ") == 10012
        assert parse_retcode(None) is None and parse_retcode("nope") is None


def decision(**overrides: object) -> RiskDecision:
    base: dict[str, object] = {
        "decision_id": "risk-1",
        "intent_id": "intent-1",
        "account_id": ACCOUNT,
        "approved": True,
        "approved_volume": 0.09,
        "symbol": "EURUSDm",
        "side": Side.BUY,
        "entry_price": 1.1,
        "stop_loss": 1.0990,
        "take_profit": 1.1030,
        "reasons": [],
        "checks": [],
        "sizing": None,
        "gates": [],
        "decided_at": NOW,
        "expires_at": NOW + timedelta(seconds=60),
    }
    base.update(overrides)
    return RiskDecision(**base)


def ctx(**overrides: object) -> ValidationContext:
    base: dict[str, object] = {
        "now": NOW,
        "connected_account_id": ACCOUNT,
        "active_account_id": ACCOUNT,
        "agent_registered": True,
        "decision": decision(),
    }
    base.update(overrides)
    return ValidationContext(**base)


def codes(req: ExecutionRequest, context: ValidationContext) -> list[RejectCode]:
    return [r.code for r in validate(req, context)]


class TestValidation:
    def test_a_clean_open_passes(self) -> None:
        assert validate(request(), ctx()) == []

    def test_account_mismatch_is_a_hard_reject(self) -> None:
        # The command is for ACC-B, the terminal is attached to ACC-A (ADR 0010).
        found = codes(
            request(account_id="ACC-B"), ctx(connected_account_id=ACCOUNT, decision=decision(account_id="ACC-B"))
        )
        assert RejectCode.ACCOUNT_MISMATCH in found

    def test_nothing_attached_nothing_executes(self) -> None:
        assert RejectCode.ACCOUNT_NOT_CONNECTED in codes(request(), ctx(connected_account_id=None))
        assert RejectCode.ACCOUNT_NOT_CONNECTED in codes(request(), ctx(account_exists=False))

    def test_automatic_commands_only_reach_the_active_account(self) -> None:
        assert RejectCode.NOT_ACTIVE_ACCOUNT in codes(request(), ctx(automatic=True, active_account_id="OTHER"))
        assert RejectCode.NOT_ACTIVE_ACCOUNT not in codes(request(), ctx(automatic=False, active_account_id="OTHER"))

    def test_expired_command(self) -> None:
        assert RejectCode.COMMAND_EXPIRED in codes(request(expires_at=NOW - timedelta(seconds=1)), ctx())
        assert RejectCode.COMMAND_EXPIRED in codes(request(expires_at=NOW), ctx())

    def test_symbol_mismatch_against_the_approved_symbol(self) -> None:
        assert RejectCode.SYMBOL_MISMATCH in codes(request(symbol="XAUUSDm"), ctx())

    def test_no_stop_no_trade(self) -> None:
        assert RejectCode.STOP_REQUIRED in codes(request(stop_loss=None), ctx())
        assert RejectCode.STOP_REQUIRED in codes(request(stop_loss=0.0), ctx())

    def test_an_open_without_a_risk_decision_is_refused(self) -> None:
        found = codes(request(risk_decision_id=None), ctx(decision=None))
        assert RejectCode.RISK_NOT_APPROVED in found
        assert RejectCode.RISK_NOT_APPROVED in codes(request(), ctx(decision=None))

    def test_a_refused_decision_cannot_be_used(self) -> None:
        refused = decision(approved=False, approved_volume=None, reasons=["news_restriction"])
        assert RejectCode.RISK_NOT_APPROVED in codes(request(), ctx(decision=refused))

    def test_a_stale_decision_is_refused(self) -> None:
        stale = decision(expires_at=NOW - timedelta(seconds=1))
        assert RejectCode.RISK_DECISION_EXPIRED in codes(request(), ctx(decision=stale))

    def test_a_decision_of_another_account_or_command_is_refused(self) -> None:
        assert RejectCode.RISK_DECISION_MISMATCH in codes(request(), ctx(decision=decision(account_id="OTHER")))
        assert RejectCode.RISK_DECISION_MISMATCH in codes(request(risk_decision_id="risk-2"), ctx())

    def test_the_command_cannot_exceed_what_was_approved(self) -> None:
        assert RejectCode.RISK_DECISION_MISMATCH in codes(request(volume=0.5), ctx())
        assert RejectCode.RISK_DECISION_MISMATCH in codes(request(side=Side.SELL, stop_loss=1.1010), ctx())
        assert RejectCode.RISK_DECISION_MISMATCH in codes(request(stop_loss=1.0980), ctx())  # looser stop on a buy
        assert validate(request(volume=0.05, stop_loss=1.0995), ctx()) == []  # smaller and tighter is fine

    def test_a_looser_stop_on_a_sell_is_refused(self) -> None:
        sell_decision = decision(side=Side.SELL, stop_loss=1.1010, take_profit=1.0970)
        looser = request(side=Side.SELL, stop_loss=1.1020, take_profit=1.0970)
        assert RejectCode.RISK_DECISION_MISMATCH in codes(looser, ctx(decision=sell_decision))

    def test_a_limit_order_needs_the_limit_capability_a_price_and_a_stop_behind_it(self) -> None:
        from trading_os.domain.strategy.intent import OrderKind

        limit = request(order_type=OrderKind.LIMIT, price=1.0995, stop_loss=1.0990)
        assert RejectCode.AGENT_CAPABILITY_MISSING in codes(limit, ctx())  # agent 1.11 announces none (ADR 0023)
        capable = ctx(agent_capabilities=frozenset({"limit"}))
        assert validate(limit, capable) == []
        assert RejectCode.INVALID_REQUEST in codes(request(order_type=OrderKind.LIMIT, price=None), capable)
        above = request(
            order_type=OrderKind.LIMIT, price=1.0995, stop_loss=1.1000
        )  # a buy whose stop is above its price
        assert RejectCode.INVALID_REQUEST in codes(above, capable)
        wrong_target = request(order_type=OrderKind.LIMIT, price=1.0995, stop_loss=1.0990, take_profit=1.0990)
        assert RejectCode.INVALID_REQUEST in codes(wrong_target, capable)

    def test_stop_orders_are_still_not_carried(self) -> None:
        from trading_os.domain.strategy.intent import OrderKind

        assert RejectCode.ORDER_TYPE_UNSUPPORTED in codes(
            request(order_type=OrderKind.STOP, price=1.1010), ctx(agent_capabilities=frozenset({"limit"}))
        )

    def test_trading_disabled_and_halted(self) -> None:
        assert RejectCode.TRADING_DISABLED in codes(request(), ctx(account_trading_enabled=False))
        assert RejectCode.HALTED in codes(request(), ctx(halted=True))

    def test_a_halt_stops_new_risk_not_the_way_out(self) -> None:
        """ADR 0033: a closing or a cancelling by a human gesture goes through a halt; everything else is still refused."""
        capable = {"decision": None, "agent_capabilities": frozenset({"close", "modify", "cancel"}), "halted": True}
        for kind, extra in (
            (CommandKind.CLOSE, {"position_id": "1"}),
            (CommandKind.PARTIAL_CLOSE, {"position_id": "1", "volume": 0.01}),
            (CommandKind.CANCEL, {"order_id": "9"}),
        ):
            exit_ = request(kind=kind, risk_decision_id=None, **extra)
            assert RejectCode.HALTED not in codes(exit_, ctx(**capable)), kind  # by hand: the halt does not stop it
            if (
                kind is not CommandKind.PARTIAL_CLOSE
            ):  # (a partial close also needs the position's numbers, ADR 0023: not about the halt)
                assert validate(exit_, ctx(**capable)) == [], kind
            assert RejectCode.HALTED in codes(exit_, ctx(automatic=True, **capable)), (
                kind
            )  # an automatic actor does not act while halted
        modify = request(
            kind=CommandKind.MODIFY, position_id="1", stop_loss=1.0995, take_profit=None, risk_decision_id=None
        )
        assert RejectCode.HALTED in codes(modify, ctx(**capable))  # a stop move is not an exit
        assert RejectCode.HALTED in codes(request(), ctx(halted=True))  # an opening is refused, as before
        assert RejectCode.HALTED in codes(request(), ctx(halted=True, automatic=True))

    def test_a_halt_does_not_lift_the_other_refusals_of_an_exit(self) -> None:
        exit_ = request(kind=CommandKind.CLOSE, position_id="1", risk_decision_id=None)
        capable = {"decision": None, "agent_capabilities": frozenset({"close"}), "halted": True}
        assert RejectCode.AGENT_UNREACHABLE in codes(exit_, ctx(agent_registered=False, **capable))
        assert RejectCode.AGENT_CAPABILITY_MISSING in codes(exit_, ctx(decision=None, halted=True))

    def test_the_disable_trading_switch_stops_risk_not_a_human_exit(self) -> None:
        """ADR 0034: switching trading off for an account refuses an opening, a stop move and any automatic command — never a closing or a
        cancelling issued by a human gesture, halted or not."""
        exit_ = request(kind=CommandKind.CLOSE, position_id="1", risk_decision_id=None)
        capable = {"decision": None, "agent_capabilities": frozenset({"close"}), "account_trading_enabled": False}
        assert RejectCode.TRADING_DISABLED not in codes(exit_, ctx(**capable))
        assert RejectCode.TRADING_DISABLED not in codes(exit_, ctx(halted=True, **capable))
        assert RejectCode.TRADING_DISABLED in codes(exit_, ctx(automatic=True, **capable))
        assert RejectCode.TRADING_DISABLED in codes(request(), ctx(account_trading_enabled=False))

    def test_no_agent_registered(self) -> None:
        assert RejectCode.AGENT_UNREACHABLE in codes(request(), ctx(agent_registered=False))

    def test_kinds_the_agent_cannot_handle_are_refused_not_sent_into_the_void(self) -> None:
        close = request(kind=CommandKind.CLOSE, position_id="987", risk_decision_id=None)
        assert RejectCode.AGENT_CAPABILITY_MISSING in codes(close, ctx(decision=None))
        capable = ctx(decision=None, agent_capabilities=frozenset({"close"}))
        assert validate(close, capable) == []

    def test_reduce_only_commands_need_no_risk_decision_but_need_their_target(self) -> None:
        capable = {"decision": None, "agent_capabilities": frozenset({"close", "modify", "cancel"})}
        assert validate(request(kind=CommandKind.CLOSE, position_id="1", risk_decision_id=None), ctx(**capable)) == []
        assert RejectCode.INVALID_REQUEST in codes(request(kind=CommandKind.CLOSE, position_id=None), ctx(**capable))
        assert RejectCode.INVALID_REQUEST in codes(request(kind=CommandKind.CANCEL, order_id=None), ctx(**capable))
        assert RejectCode.INVALID_REQUEST in codes(
            request(kind=CommandKind.PARTIAL_CLOSE, position_id="1", volume=None), ctx(**capable)
        )

    def test_every_violation_is_reported_not_only_the_first(self) -> None:
        found = codes(request(stop_loss=None, symbol="XAUUSDm"), ctx(halted=True, account_trading_enabled=False))
        assert {
            RejectCode.HALTED,
            RejectCode.TRADING_DISABLED,
            RejectCode.STOP_REQUIRED,
            RejectCode.SYMBOL_MISMATCH,
        } <= set(found)

    def test_a_command_missing_its_side_or_volume(self) -> None:
        assert RejectCode.INVALID_REQUEST in codes(request(side=None), ctx())
        assert RejectCode.INVALID_REQUEST in codes(request(volume=None), ctx())
