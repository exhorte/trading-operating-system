"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const AGENT_TONES: Record<string, PillTone> = {
  connected: "profit",
  degraded: "warning",
  disconnected: "loss",
};

export function AgentHealthPanel() {
  const { agents, account } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (agents.length === 0) {
    return (
      <Card title="Execution agents">
        <Skeleton className="h-24" />
      </Card>
    );
  }

  return (
    <Card title="Execution agents" untrusted={untrusted}>
      <ul className="flex flex-col gap-2">
        {agents.map((agent) => (
          <li
            key={agent.agentId}
            className="rounded border border-border bg-surface-elevated p-2"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium">
                {agent.agentId}
                <span className="ml-1.5 text-muted">({agent.platform})</span>
              </span>
              <StatusPill tone={AGENT_TONES[agent.state] ?? "muted"}>{agent.state}</StatusPill>
            </div>
            <dl className="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] text-muted">
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
    </Card>
  );
}
