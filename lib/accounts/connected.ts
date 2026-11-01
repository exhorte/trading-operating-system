/**
 * Which account is connected, and when a screen has nothing to show without one (ADR 0021).
 *
 * **One account is connected at a time**: the core refuses a second connection (`another_account_connected`), so the
 * connected account is also the active one. A screen that reads an account's figures has nothing to say until one is
 * connected — without this, it shows grey placeholders forever and the trader has no way to know why, or what to do.
 * These few functions only decide; the core owns the rule.
 */

import type { Account } from "@/lib/api/generated";
import type { ConnectionState } from "@/lib/realtime/store";

/** The screens where an account is registered, connected and set up: they stay open with none connected. */
const OPEN_WITHOUT_ACCOUNT = ["/account", "/settings"];

export function connectedAccount(accounts: readonly Account[]): Account | null {
  return accounts.find((account) => account.status === "CONNECTED") ?? null;
}

export function needsConnectedAccount(pathname: string): boolean {
  return !OPEN_WITHOUT_ACCOUNT.some((open) => pathname === open || pathname.startsWith(`${open}/`));
}

export interface CoreView {
  connection: ConnectionState;
  /** `null` until the core's first snapshot has arrived: before that, « no account » is not a fact yet. */
  version: string | null;
  accounts: readonly Account[];
}

/**
 * Show the connection form in place of the screen: the core has answered (so « no account connected » is a fact, not a loading
 * state), none is connected, and this screen needs one. While the core is unreachable the screen's own message stands.
 */
export function showsConnectGate(core: CoreView, pathname: string): boolean {
  const answered = core.version !== null && (core.connection === "connected" || core.connection === "degraded");
  return answered && connectedAccount(core.accounts) === null && needsConnectedAccount(pathname);
}
