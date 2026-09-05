"use client";

import type { ConnectionState } from "@/lib/contracts/enums";
import { useConnectionState } from "@/lib/realtime/provider";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const STATE_TONES: Record<ConnectionState, { tone: PillTone; pulse: boolean }> = {
  mock: { tone: "muted", pulse: false },
  connecting: { tone: "info", pulse: true },
  connected: { tone: "profit", pulse: false },
  reconnecting: { tone: "info", pulse: true },
  stale: { tone: "warning", pulse: true },
  degraded: { tone: "warning", pulse: true },
  disconnected: { tone: "loss", pulse: false },
  error: { tone: "loss", pulse: false },
};

export function ConnectionBadge() {
  const connection = useConnectionState();
  const { tone, pulse } = STATE_TONES[connection];
  return (
    <StatusPill tone={tone} pulse={pulse}>
      WS {connection}
    </StatusPill>
  );
}
