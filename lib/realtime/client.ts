import type { PreTradeTicket } from "@/lib/domain/ticket";

/**
 * Transport seam of the cockpit.
 *
 * Phase 01 ships MockRealtimeClient only. The future SignalR/WebSocket client
 * (Phase 03+) implements this same interface and feeds the same CockpitStore,
 * so swapping transports never touches UI components.
 */

export interface RealtimeClient {
  /** Open the connection and begin feeding the store. */
  start(): void;
  /** Tear down timers/sockets. Safe to call multiple times. */
  stop(): void;
  /**
   * Publish a pre-trade ticket (T04). Fire-and-forget from the caller's
   * perspective: the only proof of success is the ticket echoing back
   * through the event stream with its own ticketId (see store.ts) — a
   * silent refusal (unknown type, oversized envelope, dropped write) never
   * calls back, by design.
   */
  publishTicket(ticket: PreTradeTicket): void;
  /**
   * T02a: manual kill switch. Locks the account (persisted ledger) — never
   * sends a close_all command; the trader closes positions in MT5 themselves.
   * No-ops if already locked.
   */
  triggerKillSwitch(): void;
  /** T02a: the trader's own record of having closed positions manually. */
  acknowledgeLockout(lockoutId: string): void;
}
