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
import { SignalRRealtimeClient } from "./signalr-client";
import type { RealtimeClient } from "./client";
import { CockpitStore, EMPTY_COCKPIT_SNAPSHOT, type CockpitSnapshot } from "./store";

const CockpitStoreContext = createContext<CockpitStore | null>(null);

// Mock is the default everywhere. Local opt-ins via NEXT_PUBLIC_REALTIME_SOURCE:
//  - "backend": SignalR to the ASP.NET Core gateway (production path, ADR 0009)
//  - "live":    browser-side translation prototype (ADR 0007, superseded by backend)
function createClient(store: CockpitStore): RealtimeClient {
  const source = process.env.NEXT_PUBLIC_REALTIME_SOURCE;
  if (source === "backend") {
    const hubUrl =
      process.env.NEXT_PUBLIC_BACKEND_HUB_URL ?? "http://localhost:5080/hub/cockpit";
    return new SignalRRealtimeClient(store, hubUrl);
  }
  if (source === "live") {
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
