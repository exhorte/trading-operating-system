"""Live measurements (ADR 0035, L1): the figures are values that occurred, a hole is said and never filled, a command that
never reached the broker is not counted among the broker's answers."""

from __future__ import annotations

from datetime import datetime, timedelta

from tests.support.builders import NOW, make_command
from trading_os.cli.live_report import render_live_report
from trading_os.domain.execution.commands import CommandState, ExecutionCommand
from trading_os.domain.telemetry.live_metrics import (
    AgentLinkMetrics,
    Distribution,
    QuoteMetrics,
    command_metrics,
    distribution,
    not_measured,
    ticks_per_minute,
)


def timed(
    state: CommandState,
    *,
    sent: float | None = None,
    acknowledged: float | None = None,
    completed: float | None = None,
    command_id: str = "cmd-a",
    **changes: object,
) -> ExecutionCommand:
    """A command created at ``NOW`` whose later timestamps are given in seconds after it."""

    def at(offset: float | None) -> datetime | None:
        return None if offset is None else NOW + timedelta(seconds=offset)

    return make_command(command_id, state=state).model_copy(
        update={"sent_at": at(sent), "acknowledged_at": at(acknowledged), "completed_at": at(completed), **changes}
    )


# ------------------------------------------------------------------------------------------------------ distributions


def test_a_distribution_is_made_of_values_that_occurred() -> None:
    d = distribution(range(1, 21))  # 1 … 20
    assert (d.n, d.min, d.median, d.p95, d.max) == (20, 1, 10, 19, 20)
    assert d.median in range(1, 21) and d.p95 in range(1, 21)  # nearest rank: never between two observed values


def test_one_value_is_its_own_summary_and_no_value_is_not_measured() -> None:
    assert distribution([0.00008]) == Distribution(n=1, min=0.00008, median=0.00008, p95=0.00008, max=0.00008)
    nothing = distribution([])
    assert nothing == Distribution(n=0) and nothing.median is None  # not zero: unknown


def test_float_noise_is_rounded_away_without_moving_a_figure() -> None:
    assert distribution([1.11879 - 1.11871]).median == 0.00008


def test_a_rate_needs_two_ticks_and_a_span() -> None:
    assert ticks_per_minute(61, 60.0) == 60.0  # 60 intervals in 60 seconds
    assert ticks_per_minute(1, 60.0) is None and ticks_per_minute(0, None) is None
    assert ticks_per_minute(5, 0.0) is None


# ------------------------------------------------------------------------------------------------------ commands


def test_durations_come_from_the_brokers_answers_and_leave_simulated_commands_out() -> None:
    answered = timed(CommandState.EXECUTED, sent=0.1, acknowledged=0.4, completed=0.9, broker_retcode="10009")
    slower = timed(
        CommandState.EXECUTED, sent=0.1, acknowledged=0.6, completed=1.6, command_id="cmd-b", broker_retcode="10009"
    )
    refused = timed(CommandState.REJECTED, command_id="cmd-c", reject_code="STALE_PRICE")
    simulated = timed(CommandState.SIMULATED, sent=0.1, acknowledged=5.0, completed=9.0, command_id="cmd-d")
    metrics = command_metrics([answered, slower, refused, simulated])

    assert metrics.total == 4 and metrics.simulated == 1
    assert metrics.by_state == {"EXECUTED": 2, "REJECTED": 1, "SIMULATED": 1}
    assert metrics.reject_codes == {"STALE_PRICE": 1} and metrics.broker_retcodes == {"10009": 2}
    # the simulated command's 4.9 s acknowledgement is not counted
    assert (metrics.ack_s.n, metrics.ack_s.min, metrics.ack_s.max) == (2, 0.3, 0.5)
    assert (metrics.fill_s.min, metrics.fill_s.max) == (0.5, 1.0)
    assert (metrics.total_s.min, metrics.total_s.max) == (0.9, 1.6)


def test_timestamps_that_run_backwards_are_counted_and_left_out_never_corrected() -> None:
    backwards = timed(CommandState.EXECUTED, sent=2.0, acknowledged=1.0, completed=3.0)
    metrics = command_metrics([backwards])
    assert metrics.inconsistent == 1
    assert metrics.ack_s.n == 0  # the impossible figure is dropped…
    assert (metrics.fill_s.n, metrics.total_s.n) == (1, 1)  # …the possible ones stay


def test_a_command_still_in_flight_has_no_completion_to_measure() -> None:
    metrics = command_metrics([timed(CommandState.SENT, sent=0.1)])
    assert metrics.total == 1 and metrics.total_s.n == 0 and metrics.fill_s.n == 0 and metrics.inconsistent == 0


def test_no_command_is_an_empty_summary_not_a_zero_latency() -> None:
    metrics = command_metrics([])
    assert metrics.total == 0 and metrics.ack_s == Distribution(n=0) and metrics.by_state == {}


# ------------------------------------------------------------------------------------------------------ holes, said


def quote(symbol: str = "EURUSDm", *, ticks: int = 10, lag_n: int = 5) -> QuoteMetrics:
    return QuoteMetrics(
        symbol=symbol, ticks=ticks, spread=distribution([0.00008] * ticks),
        receipt_lag_s=distribution([0.5] * lag_n),
    )  # fmt: skip


def test_every_hole_is_named() -> None:
    none = command_metrics([])
    gaps = not_measured([quote(ticks=0, lag_n=0)], AgentLinkMetrics(connected=False), none)
    text = " | ".join(gaps)
    assert "EURUSDm: no tick stored" in text and "no quote seen by a running core" in text
    assert "no execution agent is connected" in text
    assert "constant latencyMs of 0" in text  # the agent's own figure is a constant, and is not used
    assert "no command in the window" in text and "slippage" in text


def test_an_account_the_core_is_not_connected_to_gives_no_quote_and_the_report_says_why() -> None:
    gaps = not_measured([], AgentLinkMetrics(connected=False), command_metrics([]), terminal_connected=False)
    assert "the account is not connected to the terminal" in gaps[0]


def test_a_report_that_does_not_query_the_core_says_it_does_not_see_the_link() -> None:
    gaps = not_measured([quote()], None, command_metrics([timed(CommandState.SIMULATED, command_id="cmd-s")]))
    text = " | ".join(gaps)
    assert "not observed by this report" in text and "every command in the window was SIMULATED" in text
    assert "no tick stored" not in text  # what was measured is not reported missing


def test_the_markdown_report_carries_its_numbers_its_holes_and_its_limits() -> None:
    commands = command_metrics([timed(CommandState.EXECUTED, sent=0.1, acknowledged=0.4, completed=0.9)])
    page = render_live_report(
        account_id="exness-1", start=NOW - timedelta(hours=1), end=NOW, quotes=[quote()], commands=commands
    )
    assert page.startswith("# Live measures") and "| EURUSDm | 10 |" in page
    assert "| Sent → acknowledged (core, agent, core) | 1 | 0.3 | 0.3 | 0.3 | 0.3 |" in page
    assert "## Not measured" in page and "## Reading these figures" in page
    assert "nothing was sent to a terminal or an agent" in page
