/**
 * Execution protocol contracts (ADR 0010, EA-03): the versioned vocabulary
 * OS<->agent messages carry, on top of the wire shapes in
 * lib/contracts/mt5-wire.ts. See context/execution/protocol.md.
 */

export * from "./reject-reason";
export * from "./idempotency";
