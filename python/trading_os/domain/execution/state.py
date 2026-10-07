"""Command lifecycle — an explicit transition table (ADR 0010; port of ``lib/domain/execution-state.ts``, reduced to the
states the core can actually observe).

The non-negotiable rule this file exists to enforce: **UNKNOWN never replays and never re-enters the happy path.**
Its only way out is reconciliation (UNKNOWN → RECONCILING → RECONCILED). There is no row in the table for
« UNKNOWN → SENT » or « UNKNOWN → EXECUTED », so it cannot be added by accident; an illegal move raises.

    happy path   PENDING ─SENT▶ SENT ─ACK_ACCEPTED▶ ACKNOWLEDGED ─REPORT_EXECUTED▶ EXECUTED
                 ─POSITION_CONFIRMED▶ RECONCILED
    refusals     SENT ─ACK_REJECTED▶ REJECTED · ─ACK_EXPIRED▶ EXPIRED
                 PENDING ─SEND_FAILED▶ FAILED · ─EXPIRED▶ EXPIRED · ─CANCEL_REQUESTED▶ CANCELLED
    simulated    SENT|ACKNOWLEDGED ─REPORT_SIMULATED▶ SIMULATED          failed   ACKNOWLEDGED ─REPORT_FAILED▶ FAILED
    in doubt     SENT|ACKNOWLEDGED ─LINK_LOST▶ UNKNOWN ─RECONCILIATION_STARTED▶ RECONCILING ─RECONCILED▶ RECONCILED
                 (RECONCILING ─RECONCILIATION_PENDING▶ RECONCILING: inconclusive, stays, never guesses)

The 13-state machine of the audit is folded into these: RISK_APPROVED disappears (the decision precedes the command),
RECEIVED/VALIDATING/EXECUTING are internal to the agent (not observable) and merge into ACKNOWLEDGED. Once ACKNOWLEDGED
there is **no** cancel/expire edge: an order may already be live at the broker.
"""

from __future__ import annotations

from enum import StrEnum

from trading_os.domain.execution.commands import CommandState as S
from trading_os.shared.errors import IllegalTransition


class CommandEvent(StrEnum):
    SENT = "SENT"
    SEND_FAILED = "SEND_FAILED"  # the agent could not be reached: nothing was sent
    ACK_ACCEPTED = "ACK_ACCEPTED"
    ACK_REJECTED = "ACK_REJECTED"
    ACK_EXPIRED = "ACK_EXPIRED"
    REPORT_EXECUTED = "REPORT_EXECUTED"
    REPORT_SIMULATED = "REPORT_SIMULATED"
    REPORT_FAILED = "REPORT_FAILED"  # a definite refusal only — ambiguous retcodes are LINK_LOST/UNKNOWN
    LINK_LOST = "LINK_LOST"  # silence or ambiguity after the send: the outcome is not known
    POSITION_CONFIRMED = "POSITION_CONFIRMED"
    RECONCILIATION_STARTED = "RECONCILIATION_STARTED"
    RECONCILIATION_PENDING = "RECONCILIATION_PENDING"  # attempted, inconclusive: stays RECONCILING, never guesses
    RECONCILED = "RECONCILED"
    EXPIRED = "EXPIRED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"


E = CommandEvent

_TABLE: dict[tuple[S, CommandEvent], S] = {
    (S.PENDING, E.SENT): S.SENT,
    (S.PENDING, E.SEND_FAILED): S.FAILED,
    (S.PENDING, E.EXPIRED): S.EXPIRED,
    (S.PENDING, E.CANCEL_REQUESTED): S.CANCELLED,
    (S.SENT, E.ACK_ACCEPTED): S.ACKNOWLEDGED,
    (S.SENT, E.ACK_REJECTED): S.REJECTED,
    (S.SENT, E.ACK_EXPIRED): S.EXPIRED,
    (S.SENT, E.LINK_LOST): S.UNKNOWN,
    # A final report replayed after a reconnection can overtake a lost ack: the report itself proves acceptance.
    (S.SENT, E.REPORT_EXECUTED): S.EXECUTED,
    (S.SENT, E.REPORT_SIMULATED): S.SIMULATED,
    (S.SENT, E.REPORT_FAILED): S.FAILED,
    (S.ACKNOWLEDGED, E.REPORT_EXECUTED): S.EXECUTED,
    (S.ACKNOWLEDGED, E.REPORT_SIMULATED): S.SIMULATED,
    (S.ACKNOWLEDGED, E.REPORT_FAILED): S.FAILED,
    (S.ACKNOWLEDGED, E.LINK_LOST): S.UNKNOWN,
    (S.EXECUTED, E.POSITION_CONFIRMED): S.RECONCILED,
    (S.EXECUTED, E.RECONCILIATION_STARTED): S.RECONCILING,
    (S.UNKNOWN, E.RECONCILIATION_STARTED): S.RECONCILING,
    (S.RECONCILING, E.RECONCILIATION_PENDING): S.RECONCILING,
    (S.RECONCILING, E.RECONCILED): S.RECONCILED,
}

TERMINAL_STATES = frozenset({S.RECONCILED, S.FAILED, S.REJECTED, S.EXPIRED, S.CANCELLED, S.SIMULATED})

# States in which a broker order may exist or may have been placed — a restart must never replay these.
IN_DOUBT_STATES = frozenset({S.SENT, S.ACKNOWLEDGED, S.UNKNOWN, S.RECONCILING})


def next_state(state: S, event: CommandEvent) -> S:
    """The state after ``event``; raises ``IllegalTransition`` when the table has no such edge."""
    try:
        return _TABLE[(state, event)]
    except KeyError:
        raise IllegalTransition(f"{event} is not a legal transition from {state}", code="illegal_transition") from None


def is_terminal(state: S) -> bool:
    return state in TERMINAL_STATES
