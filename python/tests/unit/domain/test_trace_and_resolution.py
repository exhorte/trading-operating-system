"""The command trace (a contract with the execution agent) and what the broker's data says about a command in doubt."""

from __future__ import annotations

from trading_os.domain.execution.resolution import (
    BrokerEvidence,
    BrokerFill,
    BrokerOrderRecord,
    resolve_command,
)
from trading_os.domain.execution.trace import command_trace, is_trace
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import Side

MAGIC = 1001
CMD = "cmd-lost-1"
TRACE = command_trace(CMD)


class TestTrace:
    def test_it_is_the_agents_algorithm(self) -> None:
        # SHA-256("abc") is the NIST test vector ba7816bf8f01cfea414140de5dae2223…; the agent keeps its first 8 bytes.
        assert command_trace("abc") == "TOS ba7816bf8f01cfea"
        assert command_trace("cmd-1") == "TOS f41e12c4bef4365a"

    def test_it_always_fits_what_a_broker_keeps_of_a_comment(self) -> None:
        assert len(command_trace("x" * 64)) == 20 < 31

    def test_it_is_recognisable_and_distinct_per_command(self) -> None:
        assert is_trace(command_trace("a")) and not is_trace("TradingOS cmd-1") and not is_trace("TOS short")
        assert command_trace("a") != command_trace("b")

    def test_it_handles_non_ascii_ids_as_utf8(self) -> None:
        assert is_trace(command_trace("commande-é-1"))


def position(**overrides: object) -> Position:
    base: dict[str, object] = {
        "position_id": "555", "account_id": "A", "symbol": "EURUSDm", "side": Side.BUY, "volume": 0.05,
        "entry_price": 1.1, "magic_number": MAGIC, "comment": TRACE,
    }  # fmt: skip
    base.update(overrides)
    return Position.model_validate(base)


def fill(**overrides: object) -> BrokerFill:
    base: dict[str, object] = {
        "position_id": "555", "order_id": "9001", "symbol": "EURUSDm", "side": Side.BUY, "volume": 0.05,
        "price": 1.1, "magic": MAGIC, "comment": TRACE,
    }  # fmt: skip
    base.update(overrides)
    return BrokerFill.model_validate(base)


def history(**overrides: object) -> BrokerOrderRecord:
    base: dict[str, object] = {
        "order_id": "9100", "symbol": "EURUSDm", "side": Side.BUY, "filled": False, "state": "REJECTED",
        "magic": MAGIC, "comment": TRACE,
    }  # fmt: skip
    base.update(overrides)
    return BrokerOrderRecord.model_validate(base)


def evidence(**parts: object) -> BrokerEvidence:
    return BrokerEvidence.model_validate({"our_magic": MAGIC, **parts})


class TestResolution:
    def test_an_open_position_with_the_trace_means_executed(self) -> None:
        found = resolve_command(CMD, evidence(positions=[position()]))
        assert (found.outcome, found.found_in) == ("executed", "position")
        assert found.broker_position_id == "555" and found.filled_volume == 0.05 and found.average_price == 1.1

    def test_a_closed_position_is_found_through_its_opening_deal(self) -> None:
        found = resolve_command(CMD, evidence(entry_deals=[fill()]))
        assert (found.outcome, found.found_in) == ("executed", "deal")
        assert found.broker_position_id == "555" and found.broker_order_id == "9001"

    def test_the_open_position_wins_over_its_deal(self) -> None:
        found = resolve_command(CMD, evidence(positions=[position(position_id="1")], entry_deals=[fill()]))
        assert found.found_in == "position" and found.broker_position_id == "1"

    def test_a_live_pending_order_is_executed_without_a_position(self) -> None:
        order = PendingOrder(
            order_id="77", account_id="A", symbol="EURUSDm", side=Side.BUY, order_type="limit", volume=0.05,
            price=1.09, magic_number=MAGIC, comment=TRACE,
        )  # fmt: skip
        found = resolve_command(CMD, evidence(pending_orders=[order]))
        assert (found.outcome, found.found_in) == ("executed", "pending_order")
        assert found.broker_position_id is None and found.filled_volume == 0.0 and found.broker_order_id == "77"

    def test_an_order_that_ended_unfilled_means_rejected(self) -> None:
        found = resolve_command(CMD, evidence(history_orders=[history(state="CANCELED")]))
        assert (found.outcome, found.found_in) == ("rejected", "order_history")
        assert "CANCELED" in found.detail and found.filled_volume == 0.0

    def test_a_filled_history_order_without_its_deal_is_not_guessed_at(self) -> None:
        # Inconsistent read (the EA skips it too): neither a rejection nor an execution can be claimed.
        found = resolve_command(CMD, evidence(history_orders=[history(filled=True, state="FILLED")]))
        assert found.outcome == "not_found"

    def test_nothing_found_is_an_answer_about_the_window_not_about_the_world(self) -> None:
        found = resolve_command(CMD, evidence())
        assert (found.outcome, found.found_in) == ("not_found", "nowhere")

    def test_other_commands_and_other_magic_numbers_are_ignored(self) -> None:
        other = command_trace("cmd-someone-else")
        foreign = evidence(
            positions=[position(comment=other), position(position_id="2", magic_number=999)],
            entry_deals=[fill(comment=other), fill(magic=999)],
            history_orders=[history(comment=other), history(magic=999)],
        )
        assert resolve_command(CMD, foreign).outcome == "not_found"

    def test_an_exit_style_comment_without_the_trace_is_not_mistaken_for_ours(self) -> None:
        assert resolve_command(CMD, evidence(positions=[position(comment="[sl 1.0990]")])).outcome == "not_found"

    def test_while_the_magic_number_is_unknown_the_trace_alone_is_the_evidence(self) -> None:
        found = resolve_command(CMD, BrokerEvidence(positions=[position(magic_number=4242)], our_magic=None))
        assert found.outcome == "executed" and found.broker_position_id == "555"
