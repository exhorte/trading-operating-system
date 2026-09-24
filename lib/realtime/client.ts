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
   * T02a: manual kill switch. Locks the account (persisted ledger) — never
   * sends a close_all command; the trader closes positions in MT5 themselves.
   * No-ops if already locked.
   */
  triggerKillSwitch(): void;
  /** T02a: the trader's own record of having closed positions manually. */
  acknowledgeLockout(lockoutId: string): void;
  /**
   * T12 incrément 2: re-read the account settings ledger into the store.
   * The backend client also does it on every accounts.settings.changed; the
   * Settings screen calls this after its own write so the mock source —
   * which receives no backend events — stays current too.
   */
  refreshAccountSettings(): void;
}
