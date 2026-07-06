"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import type { ConnectionState } from "@/lib/contracts/enums";
import { MockRealtimeClient } from "./mock-client";
import { CockpitStore, EMPTY_COCKPIT_SNAPSHOT, type CockpitSnapshot } from "./store";

const CockpitStoreContext = createContext<CockpitStore | null>(null);

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new CockpitStore());

  useEffect(() => {
    const client = new MockRealtimeClient(store);
    client.start();
    return () => client.stop();
  }, [store]);

  return (
    <CockpitStoreContext.Provider value={store}>{children}</CockpitStoreContext.Provider>
  );
}

function useCockpitStore(): CockpitStore {
  const store = useContext(CockpitStoreContext);
  if (!store) {
    throw new Error("useCockpit must be used inside <RealtimeProvider>");
  }
  return store;
}

/** Latest known cockpit state; re-renders on every applied realtime event. */
export function useCockpit(): CockpitSnapshot {
  const store = useCockpitStore();
  return useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    () => EMPTY_COCKPIT_SNAPSHOT,
  );
}

export function useConnectionState(): ConnectionState {
  return useCockpit().connection;
}

/** True when live panels should render in a degraded/untrusted style. */
export function useIsDataUntrusted(): boolean {
  const connection = useConnectionState();
  return (
    connection === "stale" ||
    connection === "degraded" ||
    connection === "disconnected" ||
    connection === "reconnecting" ||
    connection === "error"
  );
}
