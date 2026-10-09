/**
 * How a command's state is shown. The state itself is the core's — a command only moves through its state machine, and the
 * screen never re-derives one — this only gives each of the twelve a tone, in one place, so the commands feed and the file of a
 * trade colour them alike.
 */

import type { CommandState } from "@/lib/api/generated";

export type CommandTone = "profit" | "loss" | "warning" | "info" | "accent" | "muted";

export const COMMAND_STATE_TONES: Record<CommandState, CommandTone> = {
  PENDING: "muted",
  SENT: "info",
  ACKNOWLEDGED: "info",
  // Observe-mode outcome: deliberately NOT the "profit" fill tone.
  SIMULATED: "accent",
  EXECUTED: "profit",
  RECONCILED: "profit",
  UNKNOWN: "warning",
  RECONCILING: "warning",
  FAILED: "loss",
  REJECTED: "loss",
  EXPIRED: "muted",
  CANCELLED: "muted",
};
