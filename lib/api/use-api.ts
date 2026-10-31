"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useCockpitEvents } from "@/lib/realtime/provider";
import { call, type CallArgs, type Response } from "./client";
import type { EventType, OperationId } from "./generated";

export interface ApiRead<T> {
  /** The last answer. Kept while a refresh is in flight and when a refresh fails — `error` says the latter. */
  data: T | null;
  /** Why the last read failed (the core's own words), or null. */
  error: Error | null;
  /** True until the first answer or the first failure — not during a refresh. */
  loading: boolean;
  refresh: () => void;
}

export interface ApiReadOptions {
  /** Re-read when an event of one of these types arrives (after a short pause that joins a burst). */
  refreshOn?: readonly EventType[];
  /** Re-read on this period (ms) — for what no event announces. */
  pollMs?: number;
}

const SETTLE_MS = 250;

/**
 * Read one operation of the core and keep it fresh.
 *
 * `args === null` means *not yet*: nothing is asked (no active account, a form not filled in). The read is keyed by what is
 * asked, so changing the arguments asks again and an answer to an earlier question never lands on a later one. An answer to a
 * question no longer asked is dropped.
 */
export function useApi<K extends OperationId>(
  operation: K,
  args: CallArgs<K> | null,
  options: ApiReadOptions = {},
): ApiRead<Response<K>> {
  const [state, setState] = useState<{ key: string; data: Response<K> | null; error: Error | null; settled: boolean }>({
    key: "",
    data: null,
    error: null,
    settled: false,
  });
  const [nonce, setNonce] = useState(0);
  const key = args === null ? "" : `${operation}:${JSON.stringify(args)}`;
  const latestArgs = useRef(args);
  useEffect(() => {
    latestArgs.current = args;
  });

  useEffect(() => {
    const current = latestArgs.current;
    if (key === "" || current === null) {
      return;
    }
    const controller = new AbortController();
    const request = { ...current, signal: controller.signal } as CallArgs<K>;
    (call as (op: K, a: CallArgs<K>) => Promise<Response<K>>)(operation, request).then(
      (data) => {
        if (!controller.signal.aborted) {
          setState({ key, data, error: null, settled: true });
        }
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        // Keep the last answer of *this* question; an answer to another one is not an answer to this.
        setState((previous) => ({
          key,
          data: previous.key === key ? previous.data : null,
          error: error instanceof Error ? error : new Error(String(error)),
          settled: true,
        }));
      },
    );
    return () => controller.abort();
  }, [key, nonce, operation]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useCockpitEvents(options.refreshOn ?? [], () => {
    if (timer.current === null) {
      timer.current = setTimeout(() => {
        timer.current = null;
        refresh();
      }, SETTLE_MS);
    }
  });
  useEffect(
    () => () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
        timer.current = null;
      }
    },
    [],
  );

  const { pollMs } = options;
  useEffect(() => {
    if (!pollMs || key === "") {
      return;
    }
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [pollMs, key, refresh]);

  const mine = state.key === key;
  return {
    data: mine ? state.data : null,
    error: mine ? state.error : null,
    loading: key !== "" && !(mine && state.settled),
    refresh,
  };
}
