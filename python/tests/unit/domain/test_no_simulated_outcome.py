"""ADR 0041, increment 2 — there is no « simulated » outcome any more. A command is sent to the agent, or it is refused with a code: nothing is recorded as if it had been done.

OFF, OBSERVE and HALTED refuse an order (``MODE_NOT_PERMITTING``); an agent compiled in OBSERVE refuses it too (``AGENT_OBSERVE``). The *account* mode ``SIMULATED`` of the
demonstration terminal (``MT5_ENABLED=false``) is not an execution and stays.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import get_args

import trading_os
from trading_os.domain.execution.close_all import CloseAllItemStatus
from trading_os.domain.execution.commands import CommandState
from trading_os.domain.execution.reasons import RejectCode
from trading_os.domain.execution.retcodes import NOT_SENT_MARKER, RetcodeClass, classify_failed_report
from trading_os.domain.execution.state import CommandEvent
from trading_os.infrastructure.mt5.wire import ExecutionReport, decode_line

CORE = Path(trading_os.__file__).parent


def test_a_command_is_never_in_a_simulated_state() -> None:
    assert "SIMULATED" not in {state.value for state in CommandState}
    assert not {event.value for event in CommandEvent} & {"SIMULATED_LOCALLY", "REPORT_SIMULATED"}


def test_a_closing_batch_has_no_simulated_item() -> None:
    assert "SIMULATED" not in {status.value for status in CloseAllItemStatus}


def test_the_two_ways_an_order_is_refused_without_a_broker_have_their_codes() -> None:
    assert RejectCode.MODE_NOT_PERMITTING.value == "MODE_NOT_PERMITTING"
    assert RejectCode.AGENT_OBSERVE.value == "AGENT_OBSERVE"


def test_no_module_of_the_core_records_an_order_as_simulated() -> None:
    pattern = re.compile(
        r"CommandState\.SIMULATED|CloseAllItemStatus\.SIMULATED|SIMULATED_LOCALLY|REPORT_SIMULATED|kind=\"simulated\"|ObserveSender|simulated_only"
    )
    offenders = {
        str(path.relative_to(CORE))
        for path in CORE.rglob("*.py")
        if "(" not in path.name and pattern.search(path.read_text(encoding="utf-8"))
    }
    assert not offenders, offenders


def test_the_wire_no_longer_types_a_simulated_report_status() -> None:
    assert "SIMULATED" not in get_args(ExecutionReport.model_fields["status"].annotation)


def _report_line(status: str, detail: str = "") -> str:
    return json.dumps(
        {
            "type": "execution.report",
            "accountId": "1000001",
            "id": "x",
            "commandId": "cmd-old-1",
            "status": status,
            "detail": detail,
        }
    )


def test_an_agent_before_1_15_that_still_says_simulated_is_read_as_a_refusal_where_nothing_was_sent() -> None:
    frame = decode_line(
        _report_line("SIMULATED", "SIMULATED CLOSE 0.01 lot of position 7 EURUSDm (mode observe, no broker order)")
    )
    report = frame.message
    assert isinstance(report, ExecutionReport)
    assert report.status == "FAILED"  # never a fill, never UNKNOWN
    assert report.detail.startswith("AGENT_OBSERVE:")
    assert NOT_SENT_MARKER in report.detail
    assert classify_failed_report(report.broker_retcode, report.detail) is RetcodeClass.FAILURE


def test_the_other_report_statuses_are_read_as_they_were() -> None:
    for status in ("FILLED", "REJECTED", "FAILED", "CLOSED"):
        frame = decode_line(_report_line(status, "as sent"))
        assert isinstance(frame.message, ExecutionReport)
        assert frame.message.status == status and frame.message.detail == "as sent"
