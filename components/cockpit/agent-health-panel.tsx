"use client";

import { Cpu } from "lucide-react";
import type { AccountStatus } from "@/lib/api/generated";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const TERMINAL_TONES: Record<AccountStatus, PillTone> = {
  CONNECTED: "profit",
  CONNECTING: "warning",
  ERROR: "loss",
  DISCONNECTED: "muted",
};

const TERMINAL_LABELS: Record<AccountStatus, string> = {
  CONNECTED: "connected",
  CONNECTING: "connecting",
  ERROR: "error",
  DISCONNECTED: "detached",
};

/**
 * Two different links, deliberately shown apart: the core's READ-ONLY look at
 * the terminal (it can read an account, never order), and the EA-05 execution
 * agent's own TCP link (the only way an order could ever leave). Reading the
 * first as the second is the bug that let the cockpit imply an order could
 * reach MT5 while no agent existed (corrected 2026-09-18) — they stay two rows.
 */
export function AgentHealthPanel() {
  const { registered, account, executionAgentConnected, agent } = useCockpit();
  const untrusted = useIsDataUntrusted();

  return (
    <Panel
      title="MT5 links"
      description="agent d'exécution et lecture du terminal"
      icon={Cpu}
      untrusted={untrusted}
    >
      <div className="flex items-center justify-between gap-2 rounded-lg border bg-muted/40 px-3 py-2.5">
        <span className="text-sm font-medium">
          Execution agent
          <span className="ml-1.5 font-normal text-muted-foreground">(EA-05)</span>
        </span>
        <StatusPill tone={executionAgentConnected ? "profit" : "loss"}>
          {executionAgentConnected ? `connected · ${agent?.mode ?? "?"}` : "no agent"}
        </StatusPill>
      </div>

      <p className="mt-4 mb-2 text-xs font-medium tracking-wider text-muted-foreground uppercase">
        Terminal MT5 (read-only)
      </p>
      {registered ? (
        <div className="rounded-lg border bg-muted/40 px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium">
              {registered.name}
              <span className="ml-1.5 font-normal text-muted-foreground">({registered.platform})</span>
            </span>
            <StatusPill tone={TERMINAL_TONES[registered.status]}>{TERMINAL_LABELS[registered.status]}</StatusPill>
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-sm text-muted-foreground">
            <dt>Account</dt>
            <dd className="text-right text-foreground">{account?.label ?? registered.login}</dd>
            <dt>Server</dt>
            <dd className="text-right text-foreground">{registered.server}</dd>
            <dt>Last read</dt>
            <dd className="tnum text-right text-foreground">{account ? formatClockTime(account.observedAt) : "—"}</dd>
          </dl>
          {registered.statusDetail && <p className="mt-2 text-xs text-destructive">{registered.statusDetail}</p>}
        </div>
      ) : (
        <p className="rounded-lg border border-dashed px-3 py-4 text-center text-sm text-muted-foreground">
          Aucun compte actif — enregistre-en un dans Settings, puis rattache-le dans Account.
        </p>
      )}
    </Panel>
  );
}
