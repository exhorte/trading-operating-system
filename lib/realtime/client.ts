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
}
