/**
 * Typed rejection vocabulary for the execution protocol (ADR 0010, EA-03).
 * A command's ack/report `reason` was free text before this; the codes below
 * are the ones this repo can actually raise today. Codes named in later
 * fiches (e.g. `SYMBOL_MISMATCH`, EA-04's symbol registry) are documented in
 * context/execution/protocol.md but not added here until the gate that
 * raises them exists — an enum with more codes than the code that fires them
 * would be a promise this repo doesn't keep yet.
 */

export type CommandRejectCode =
  /** The command's accountId does not match the agent's account. Never
   *  executed "at best" — ADR 0010 is explicit that this is a hard reject. */
  | "ACCOUNT_MISMATCH"
  /** The agent is not in `observe` mode (today the only mode this repo can
   *  guarantee is safe); see CockpitHub.SubmitCommand. */
  | "MODE_NOT_OBSERVE"
  /** The command could not be delivered to the agent at all. */
  | "AGENT_UNREACHABLE"
  /** A command was built without a valid, matching risk approval. */
  | "RISK_NOT_APPROVED";

export interface CommandRejection {
  code: CommandRejectCode;
  /** Human-readable detail for the audit trail — never the sole record. */
  detail: string;
}
