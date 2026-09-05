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
import type { ConnectionState } from "@/lib/contracts/enums";
import type { PreTradeTicket } from "@/lib/domain/ticket";
import { MockRealtimeClient } from "./mock-client";
import { SignalRRealtimeClient } from "./signalr-client";
import type { RealtimeClient } from "./client";
import { CockpitStore, EMPTY_COCKPIT_SNAPSHOT, type CockpitSnapshot } from "./store";

const CockpitStoreContext = createContext<CockpitStore | null>(null);

interface RealtimeActions {
  publishTicket: (ticket: PreTradeTicket) => void;
  triggerKillSwitch: () => void;
  acknowledgeLockout: (lockoutId: string) => void;
}

const RealtimeActionsContext = createContext<RealtimeActions | null>(null);

// Mock is the default everywhere. NEXT_PUBLIC_REALTIME_SOURCE="backend" opts
// into the production path: SignalR to the ASP.NET Core gateway (ADR 0009).
// The former "live" browser-side translation prototype (ADR 0007) was
// superseded by the backend and deleted after live validation.
function createClient(store: CockpitStore): RealtimeClient {
  if (process.env.NEXT_PUBLIC_REALTIME_SOURCE === "backend") {
    const hubUrl =
      process.env.NEXT_PUBLIC_BACKEND_HUB_URL ?? "http://localhost:5080/hub/cockpit";
    return new SignalRRealtimeClient(store, hubUrl);
  }
  return new MockRealtimeClient(store);
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const [store] = useState(() => new CockpitStore());
  const clientRef = useRef<RealtimeClient | null>(null);

  useEffect(() => {
    const client = createClient(store);
    clientRef.current = client;
    client.start();
    return () => {
      client.stop();
      clientRef.current = null;
    };
  }, [store]);

  // Stable identity: the ref is what may change (reconnects, transport
  // swaps), the action function passed down never needs to.
  const actions = useMemo<RealtimeActions>(
    () => ({
      publishTicket: (ticket) => clientRef.current?.publishTicket(ticket),
      triggerKillSwitch: () => clientRef.current?.triggerKillSwitch(),
      acknowledgeLockout: (lockoutId) => clientRef.current?.acknowledgeLockout(lockoutId),
    }),
    [],
  );

  return (
    <CockpitStoreContext.Provider value={store}>
      <RealtimeActionsContext.Provider value={actions}>{children}</RealtimeActionsContext.Provider>
    </CockpitStoreContext.Provider>
  );
}

function useRealtimeActions(): RealtimeActions {
  const actions = useContext(RealtimeActionsContext);
  if (!actions) {
    throw new Error("realtime action hooks must be used inside <RealtimeProvider>");
  }
  return actions;
}

/** T04: publish a pre-trade ticket through whichever transport is active. */
export function usePublishTicket(): (ticket: PreTradeTicket) => void {
  return useRealtimeActions().publishTicket;
}

/** T02a: manual kill switch — locks the account, no close_all command. */
export function useTriggerKillSwitch(): () => void {
  return useRealtimeActions().triggerKillSwitch;
}

/** T02a: acknowledge having closed positions manually. */
export function useAcknowledgeLockout(): (lockoutId: string) => void {
  return useRealtimeActions().acknowledgeLockout;
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
