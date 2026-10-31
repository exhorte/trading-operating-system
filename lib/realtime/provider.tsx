"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { CockpitEvent, EventType } from "@/lib/api/generated";
import { CockpitController } from "./controller";
import { CockpitStore, EMPTY_COCKPIT_SNAPSHOT, type CockpitSnapshot, type ConnectionState } from "./store";

const CockpitStoreContext = createContext<CockpitStore | null>(null);

interface CockpitActions {
  engageKillSwitch: () => Promise<void>;
  acknowledgeLockout: (lockoutId: string) => Promise<void>;
}

const CockpitActionsContext = createContext<CockpitActions | null>(null);

/**
 * The cockpit's live link to the core, for the whole app: one store, one stream. The page never talks to MT5 or to a broker —
 * only to the core (ADR 0016), which is the one place a trading fact is decided.
 */
export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new CockpitStore());
  const [controller] = useState(() => new CockpitController(store));

  useEffect(() => {
    controller.start();
    return () => controller.stop();
  }, [controller]);

  // Stable identity: the controller is, so the functions passed down never need to change.
  const actions = useMemo<CockpitActions>(
    () => ({
      engageKillSwitch: () => controller.engageKillSwitch(),
      acknowledgeLockout: (lockoutId) => controller.acknowledgeLockout(lockoutId),
    }),
    [controller],
  );

  return (
    <CockpitStoreContext.Provider value={store}>
      <CockpitActionsContext.Provider value={actions}>{children}</CockpitActionsContext.Provider>
    </CockpitStoreContext.Provider>
  );
}

function useActions(): CockpitActions {
  const actions = useContext(CockpitActionsContext);
  if (!actions) {
    throw new Error("cockpit action hooks must be used inside <RealtimeProvider>");
  }
  return actions;
}

/** T02a: the manual kill switch — locks the account in the core's ledger; no close command exists. Rejects with the core's refusal. */
export function useTriggerKillSwitch(): () => Promise<void> {
  return useActions().engageKillSwitch;
}

/** T02a/T02c: acknowledge an untimed lockout — the only way one is lifted. */
export function useAcknowledgeLockout(): (lockoutId: string) => Promise<void> {
  return useActions().acknowledgeLockout;
}

/** T02c: dismiss a live lockout-violation notice — local to this tab; the fact itself is already in the journal. */
export function useDismissLockoutViolation(): (brokerPositionId: string) => void {
  const store = useCockpitStore();
  return (brokerPositionId) => store.dismissLockoutViolation(brokerPositionId);
}

export function useCockpitStore(): CockpitStore {
  const store = useContext(CockpitStoreContext);
  if (!store) {
    throw new Error("useCockpit must be used inside <RealtimeProvider>");
  }
  return store;
}

/** Latest known cockpit state; re-renders when what a screen can show changes. */
export function useCockpit(): CockpitSnapshot {
  const store = useCockpitStore();
  return useSyncExternalStore(store.subscribe, store.getSnapshot, () => EMPTY_COCKPIT_SNAPSHOT);
}

export function useConnectionState(): ConnectionState {
  return useCockpit().connection;
}

/** True when live panels should render in a degraded/untrusted style: the link is not a live one, or the core says it is unwell. */
export function useIsDataUntrusted(): boolean {
  const connection = useConnectionState();
  return (
    connection === "stale" ||
    connection === "degraded" ||
    connection === "disconnected" ||
    connection === "reconnecting"
  );
}

/**
 * Run `handler` when an event of one of these types arrives — the way a screen that reads something over HTTP learns that what
 * it shows may have changed (a trade closed, a proposal evaluated…). The handler may change on every render; the subscription
 * does not.
 */
export function useCockpitEvents(types: readonly EventType[], handler: (frame: CockpitEvent) => void): void {
  const store = useCockpitStore();
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  const key = types.join("|");
  useEffect(() => {
    const wanted = new Set<string>(key === "" ? [] : key.split("|"));
    return store.onEvent((frame) => {
      if (wanted.has(frame.type)) {
        latest.current(frame);
      }
    });
  }, [store, key]);
}
