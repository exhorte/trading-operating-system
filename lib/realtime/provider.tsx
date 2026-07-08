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
import { LiveRealtimeClient } from "./live-client";
import type { RealtimeClient } from "./client";
import { CockpitStore, EMPTY_COCKPIT_SNAPSHOT, type CockpitSnapshot } from "./store";

const CockpitStoreContext = createContext<CockpitStore | null>(null);

// Mock is the default everywhere. Opt into the live MT5 observe prototype
// locally with NEXT_PUBLIC_REALTIME_SOURCE=live (see context/realtime/live_prototype.md).
function createClient(store: CockpitStore): RealtimeClient {
  if (process.env.NEXT_PUBLIC_REALTIME_SOURCE === "live") {
    const url = process.env.NEXT_PUBLIC_MT5_WS_URL ?? "ws://localhost:8765";
    return new LiveRealtimeClient(store, url);
  }
  return new MockRealtimeClient(store);
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new CockpitStore());

  useEffect(() => {
    const client = createClient(store);
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
