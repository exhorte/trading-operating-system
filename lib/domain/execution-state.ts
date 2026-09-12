/**
 * Command lifecycle state machine (ADR 0010, EA-03). Twelve states: eight on
 * the happy path (COMMAND_CREATED ... RECONCILED) plus four ordinary
 * terminals (REJECTED, EXPIRED, FAILED, CANCELLED) and UNKNOWN, which is
 * first-class, not an error path.
 *
 * The non-negotiable rule this file exists to enforce: UNKNOWN never
 * replays and never re-enters the happy path. Its only legal exit is
 * RECONCILED — encoded here so a transition like UNKNOWN -> EXECUTING is not
 * a bug to avoid, it is a case `transition()` cannot return `ok: true` for.
 * Full narrative and the crash-recovery table per transition:
 * context/execution/state-machine.md.
 *
 * Pure — no clock, no I/O, no persistence. Deciding *when* to fire an event
 * (timeouts, reconnects, broker replies) belongs to the caller.
 */

export type CommandLifecycleState =
  | "COMMAND_CREATED"
  | "RISK_APPROVED"
  | "SENT_TO_MT5"
  | "RECEIVED"
  | "VALIDATING"
  | "EXECUTING"
  | "EXECUTED"
  | "RECONCILED"
  | "REJECTED"
  | "EXPIRED"
  | "FAILED"
  | "CANCELLED"
  | "UNKNOWN";

/** States with no legal outgoing transition at all. UNKNOWN is deliberately
 *  excluded: it has exactly one legal exit (see `transition`). */
export const TERMINAL_STATES: ReadonlySet<CommandLifecycleState> = new Set([
  "RECONCILED",
  "REJECTED",
  "EXPIRED",
  "FAILED",
  "CANCELLED",
]);

export type CommandLifecycleEvent =
  | { kind: "RISK_APPROVED" }
  | { kind: "RISK_REJECTED"; detail: string }
  | { kind: "SENT" }
  | { kind: "SEND_FAILED"; detail: string }
  | { kind: "ACK_ACCEPTED" }
  | { kind: "ACK_REJECTED"; detail: string }
  /** The link dies between send and ack: no ACK will ever arrive for this
   *  attempt. First-order entry into UNKNOWN (ADR 0010). */
  | { kind: "LINK_LOST" }
  | { kind: "VALIDATION_STARTED" }
  | { kind: "VALIDATION_PASSED" }
  | { kind: "VALIDATION_FAILED"; detail: string }
  | { kind: "EXECUTION_REPORTED" }
  | { kind: "EXECUTION_FAILED"; detail: string }
  /** The link dies between OrderSend and the report (EA-06's "worst
   *  moment" test). Second entry point into UNKNOWN. */
  | { kind: "EXECUTION_LINK_LOST" }
  /** Reconciliation concluded. `outcome` records what was found; the state
   *  machine only cares that UNKNOWN is now resolved. */
  | { kind: "RECONCILED"; outcome: "executed" | "rejected" | "not_found" }
  /** Reconciliation was attempted but is still inconclusive — stays UNKNOWN.
   *  Not a transition into a new state, never a replay. */
  | { kind: "RECONCILIATION_PENDING" }
  | { kind: "EXPIRED" }
  | { kind: "CANCEL_REQUESTED" };

export interface TransitionOk {
  ok: true;
  state: CommandLifecycleState;
}

export interface TransitionIllegal {
  ok: false;
  from: CommandLifecycleState;
  event: CommandLifecycleEvent["kind"];
  reason: string;
}

export type TransitionResult = TransitionOk | TransitionIllegal;

function ok(state: CommandLifecycleState): TransitionOk {
  return { ok: true, state };
}

function illegal(
  from: CommandLifecycleState,
  event: CommandLifecycleEvent,
): TransitionIllegal {
  return {
    ok: false,
    from,
    event: event.kind,
    reason: `${event.kind} is not a legal transition from ${from}`,
  };
}

/** Applies one event to one state. Never throws: an illegal move is a value
 *  (`ok: false`), not an exception, so callers must look at the result. */
export function transition(
  from: CommandLifecycleState,
  event: CommandLifecycleEvent,
): TransitionResult {
  switch (from) {
    case "COMMAND_CREATED":
      if (event.kind === "RISK_APPROVED") return ok("RISK_APPROVED");
      if (event.kind === "RISK_REJECTED") return ok("REJECTED");
      if (event.kind === "EXPIRED") return ok("EXPIRED");
      return illegal(from, event);

    case "RISK_APPROVED":
      if (event.kind === "SENT") return ok("SENT_TO_MT5");
      if (event.kind === "SEND_FAILED") return ok("FAILED");
      if (event.kind === "CANCEL_REQUESTED") return ok("CANCELLED");
      if (event.kind === "EXPIRED") return ok("EXPIRED");
      return illegal(from, event);

    case "SENT_TO_MT5":
      if (event.kind === "ACK_ACCEPTED") return ok("RECEIVED");
      if (event.kind === "ACK_REJECTED") return ok("REJECTED");
      if (event.kind === "LINK_LOST") return ok("UNKNOWN");
      if (event.kind === "CANCEL_REQUESTED") return ok("CANCELLED");
      if (event.kind === "EXPIRED") return ok("EXPIRED");
      return illegal(from, event);

    case "RECEIVED":
      if (event.kind === "VALIDATION_STARTED") return ok("VALIDATING");
      if (event.kind === "CANCEL_REQUESTED") return ok("CANCELLED");
      if (event.kind === "EXPIRED") return ok("EXPIRED");
      return illegal(from, event);

    case "VALIDATING":
      if (event.kind === "VALIDATION_PASSED") return ok("EXECUTING");
      if (event.kind === "VALIDATION_FAILED") return ok("REJECTED");
      if (event.kind === "CANCEL_REQUESTED") return ok("CANCELLED");
      if (event.kind === "EXPIRED") return ok("EXPIRED");
      return illegal(from, event);

    case "EXECUTING":
      // No CANCEL_REQUESTED, no EXPIRED here: once validation passed, an
      // order may already be live at the broker. Only a broker-truth event
      // (reported, failed) or losing the link moves this state forward.
      if (event.kind === "EXECUTION_REPORTED") return ok("EXECUTED");
      if (event.kind === "EXECUTION_FAILED") return ok("FAILED");
      if (event.kind === "EXECUTION_LINK_LOST") return ok("UNKNOWN");
      return illegal(from, event);

    case "EXECUTED":
      if (event.kind === "RECONCILED") return ok("RECONCILED");
      return illegal(from, event);

    case "UNKNOWN":
      // The one non-negotiable rule (ADR 0010): reconciliation is the only
      // way out, and an inconclusive attempt leaves the command UNKNOWN
      // rather than guessing. No event here ever reaches EXECUTING,
      // RECEIVED, or any other happy-path state — that branch does not
      // exist in this switch, so it cannot be added by accident.
      if (event.kind === "RECONCILED") return ok("RECONCILED");
      if (event.kind === "RECONCILIATION_PENDING") return ok("UNKNOWN");
      return illegal(from, event);

    case "REJECTED":
    case "EXPIRED":
    case "FAILED":
    case "CANCELLED":
    case "RECONCILED":
      // Terminal: nothing moves a command again once it lands here.
      return illegal(from, event);
  }
}

export function isTerminal(state: CommandLifecycleState): boolean {
  return TERMINAL_STATES.has(state);
}
