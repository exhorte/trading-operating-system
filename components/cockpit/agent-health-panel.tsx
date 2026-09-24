"use client";

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
    <div className="flex items-center justify-between gap-2 rounded border border-border bg-muted p-2">
      <span className="text-xs font-medium">
        Execution agent
        <span className="ml-1.5 text-muted-foreground">(EA-05)</span>
      </span>
      <StatusPill tone={executionAgentConnected ? "profit" : "loss"}>
        {executionAgentConnected ? "connected" : "no agent"}
      </StatusPill>
    </div>
  );

  if (agents.length === 0) {
    return (
      <Panel title="MT5 links">
        {executionRow}
        <Skeleton className="mt-2 h-16" />
      </Panel>
    );
  }

  return (
    <Panel title="MT5 links" untrusted={untrusted}>
      {executionRow}
      <p className="mt-2 mb-1 text-xs uppercase tracking-wide text-muted-foreground">
        Observer (read-only)
      </p>
      <ul className="flex flex-col gap-2">
        {agents.map((agent) => (
          <li
            key={agent.agentId}
            className="rounded border border-border bg-muted p-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium">
                {agent.agentId}
                <span className="ml-1.5 text-muted-foreground">({agent.platform})</span>
              </span>
              <StatusPill tone={AGENT_TONES[agent.state] ?? "muted"}>{agent.state}</StatusPill>
            </div>
            <dl className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <dt>Account</dt>
              <dd className="text-right text-foreground">{account?.label ?? agent.accountId}</dd>
              <dt>Latency</dt>
              <dd className="tnum text-right text-foreground">{agent.latencyMs} ms</dd>
              <dt>Last heartbeat</dt>
              <dd className="tnum text-right text-foreground">
                {formatClockTime(agent.lastHeartbeatAt)}
              </dd>
              <dt>Version</dt>
              <dd className="text-right text-foreground">{agent.version}</dd>
            </dl>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
