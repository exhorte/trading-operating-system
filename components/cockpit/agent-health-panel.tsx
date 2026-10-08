"use client";

import { Cpu } from "lucide-react";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const AGENT_TONES: Record<string, PillTone> = {
  connected: "profit",
  degraded: "warning",
  disconnected: "loss",
};

/**
 * Two different links, deliberately shown apart since 2026-09-18: the list
 * below is the READ-ONLY observer's hello (GatewayState only ever learns
 * about that one), while the execution agent's real TCP state comes from
 * Mt5AgentServer. Titling the observer "Execution agents" is what let the
 * cockpit imply an order could reach MT5 while no EA-05 agent existed.
 */
export function AgentHealthPanel() {
  const { agents, account, executionAgentConnected } = useCockpit();
  const untrusted = useIsDataUntrusted();

  const executionRow = (
    <div className="flex items-center justify-between gap-2 rounded-lg border bg-muted/40 px-3 py-2.5">
      <span className="text-sm font-medium">
        Execution agent
        <span className="ml-1.5 font-normal text-muted-foreground">(EA-05)</span>
      </span>
      <StatusPill tone={executionAgentConnected ? "profit" : "loss"}>
        {executionAgentConnected ? "connected" : "no agent"}
      </StatusPill>
    </div>
  );

  if (agents.length === 0) {
    return (
      <Panel title="MT5 links" description="agent d'exécution et observateur" icon={Cpu}>
        {executionRow}
        <Skeleton className="mt-3 h-16" />
      </Panel>
    );
  }

  return (
    <Panel title="MT5 links" description="agent d'exécution et observateur" icon={Cpu} untrusted={untrusted}>
      {executionRow}
      <p className="mt-4 mb-2 text-xs font-medium tracking-wider text-muted-foreground uppercase">
        Observer (read-only)
      </p>
      <ul className="flex flex-col gap-2">
        {agents.map((agent) => (
          <li key={agent.agentId} className="rounded-lg border bg-muted/40 px-3 py-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">
                {agent.agentId}
                <span className="ml-1.5 font-normal text-muted-foreground">({agent.platform})</span>
              </span>
              <StatusPill tone={AGENT_TONES[agent.state] ?? "muted"}>{agent.state}</StatusPill>
            </div>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-sm text-muted-foreground">
              <dt>Account</dt>
              <dd className="text-right text-foreground">{account?.label ?? agent.accountId}</dd>
              <dt>Latency</dt>
              <dd className="tnum text-right text-foreground">{agent.latencyMs} ms</dd>
              <dt>Last heartbeat</dt>
              <dd className="tnum text-right text-foreground">{formatClockTime(agent.lastHeartbeatAt)}</dd>
              <dt>Version</dt>
              <dd className="text-right text-foreground">{agent.version}</dd>
            </dl>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
