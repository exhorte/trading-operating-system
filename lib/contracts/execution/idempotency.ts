/**
 * Idempotency rule (ADR 0010): a command replayed under the same commandId
 * must return the result already recorded for it — never execute a second
 * time, never produce a second position. This module states the rule as a
 * pure function over an explicit, caller-owned store so it is testable in
 * memory, without a real store: EA-05 persists this to disk (the agent must
 * survive a restart), EA-06 adds reconciliation on top. Neither exists yet;
 * this is the contract they must both honor.
 */

export interface IdempotentAttempt<TResult> {
  /** What the caller should act on: freshly computed, or the prior result. */
  result: TResult;
  /** True when `result` came from a prior attempt — nothing was re-executed. */
  wasReplay: boolean;
}

/**
 * Looks up `commandId` in `store`. On a miss, calls `execute()` once and
 * returns a store with the new result recorded. On a hit, `execute` is never
 * called — the previously recorded result comes back unchanged. Pure: the
 * input store is never mutated, a new Map is returned.
 */
export function recordOrReplay<TResult>(
  store: ReadonlyMap<string, TResult>,
  commandId: string,
  execute: () => TResult,
): { attempt: IdempotentAttempt<TResult>; nextStore: Map<string, TResult> } {
  const previous = store.get(commandId);
  if (previous !== undefined) {
    return {
      attempt: { result: previous, wasReplay: true },
      nextStore: new Map(store),
    };
  }

  const result = execute();
  const nextStore = new Map(store);
  nextStore.set(commandId, result);
  return { attempt: { result, wasReplay: false }, nextStore };
}
