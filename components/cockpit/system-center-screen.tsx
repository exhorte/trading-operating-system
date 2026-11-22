"use client";

import { useState } from "react";
import { Copy, Cpu, Info, RefreshCw } from "lucide-react";
import { useApi } from "@/lib/api/use-api";
import type { Mt5TerminalView } from "@/lib/api/generated";
import {
  authorizationLine,
  commandsFor,
  COMMAND_PREFIX,
  heartbeatLine,
  LIGHT_LABELS,
  lightTone,
  openConditions,
  READ_ONLY_NOTE,
  stateLabel,
  summaryLine,
  VERDICT_LABELS,
  verdictTone,
} from "@/lib/cockpit/system-center";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

const POLL_MS = 5000;

/**
 * System Center (ADR 0039 § 8) — the MetaTrader terminals the launcher registered, their agents, and whether each is
 * technically ready. **Read-only**: it reads `GET /api/system/center` and shows it. The actions that change a file or a process
 * are commands to copy, not buttons (opening the API to processes needs its own ADR and a confirmed human gesture).
 */
export function SystemCenterScreen() {
  const center = useApi("system_center", {}, { pollMs: POLL_MS });
  const data = center.data;

  if (center.loading || data === null) {
    return center.error ? (
      <Panel title="System Center" icon={Cpu}>
        <p role="alert" className="text-sm text-destructive">
          Le cœur n&apos;a pas répondu : {center.error.message}
        </p>
      </Panel>
    ) : (
      <Skeleton className="h-40 w-full" />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <p className="flex items-start gap-2 rounded-lg bg-muted px-4 py-2.5 text-sm text-muted-foreground">
        <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
        <span>{READ_ONLY_NOTE}</span>
      </p>
      <Panel
        title="Vue d'ensemble"
        description={summaryLine(data)}
        icon={Cpu}
        actions={
          <Button variant="outline" size="sm" onClick={() => center.refresh()}>
            <RefreshCw className="size-4" aria-hidden /> Relire
          </Button>
        }
      >
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <Fact label="Cœur" value={data.coreStatus} />
          <Fact label="Mode du système" value={data.executionMode} />
          <Fact label="Agents connectés" value={String(data.agentsConnected)} />
          <Fact label="Workers MT5 vivants" value={String(data.mt5WorkersAlive)} />
        </dl>
        {data.registryProblem ? (
          <p role="alert" className="mt-3 text-sm text-destructive">
            {data.registryProblem}
          </p>
        ) : null}
      </Panel>

      {data.terminals.map((item) => (
        <TerminalCard key={item.terminal.terminalId} item={item} />
      ))}

      {data.unregisteredAgents.length > 0 ? (
        <Panel title="Agents que aucun terminal n'a déclarés" description="Connectés au cœur, mais sans terminal enregistré pour leur login.">
          <ul className="flex flex-col gap-1 text-sm">
            {data.unregisteredAgents.map((agent) => (
              <li key={agent.login}>
                login {agent.login} — agent {agent.agentVersion}, battement {heartbeatLine(agent.heartbeatAgeS)}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <Panel title="Événements récents du lanceur" description="Les textes sont masqués par le lanceur avant d'être écrits.">
        {data.recentEvents.length === 0 ? (
          <p className="text-sm text-muted-foreground">Aucun événement.</p>
        ) : (
          <ol className="flex flex-col gap-1 font-mono text-xs">
            {[...data.recentEvents].reverse().map((event, index) => (
              <li key={`${event.occurredAt ?? "?"}-${index}`}>
                <span className="text-muted-foreground">{event.occurredAt ?? "?"}</span> {event.type}
                {event.diagnostic ? ` — ${event.diagnostic}` : ""}
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function TerminalCard({ item }: { item: Mt5TerminalView }) {
  const { terminal, readiness, agent } = item;
  const open = openConditions(item);
  return (
    <Panel
      title={`${terminal.label} — ${terminal.terminalId.slice(0, 8)}`}
      description={`${terminal.installPath} · données : ${terminal.dataPath}`}
      icon={Cpu}
      actions={<StatusPill tone={verdictTone(readiness.verdict)}>{VERDICT_LABELS[readiness.verdict] ?? readiness.verdict}</StatusPill>}
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <Fact label="Dernier état journalisé" value={stateLabel(terminal.lastState)} />
        <Fact label="Compte Trading OS" value={terminal.declared.accountId ?? "non déclaré"} />
        <Fact label="Login attendu" value={terminal.declared.expectedLogin ?? "non déclaré"} />
        <Fact
          label="Graphique déclaré"
          value={terminal.declared.chartSymbol ? `${terminal.declared.chartSymbol} ${terminal.declared.chartPeriod ?? ""}` : "non déclaré"}
        />
        <Fact label="Produit déclaré" value={terminal.declared.product ?? "non déclaré"} />
        <Fact label="Agent déployé" value={terminal.deployment ? terminal.deployment.agentVersion : "aucun"} />
        <Fact label="Hello de l'agent" value={item.helloReceived ? "reçu" : "aucun"} />
        <Fact label="Dernier battement" value={heartbeatLine(agent?.heartbeatAgeS)} />
        <Fact label="Version de protocole" value={agent?.protocolVersion != null ? String(agent.protocolVersion) : "non rapportée"} />
      </dl>

      {readiness.headerCode ? (
        <p role="alert" className="mt-3 text-sm font-semibold text-destructive">
          {readiness.headerCode}
        </p>
      ) : null}
      <p className="mt-3 text-sm">
        <span className="text-muted-foreground">Execution Authorization : </span>
        <strong>{authorizationLine(item)}</strong>{" "}
        <span className="text-muted-foreground">(ligne séparée : ce n&apos;est pas la préparation)</span>
      </p>

      {open.length > 0 ? (
        <ul className="mt-3 flex flex-col gap-1 text-sm">
          {open.map((condition) => (
            <li key={condition.code} className="flex items-start gap-2">
              <StatusPill tone={lightTone(condition.light)}>{LIGHT_LABELS[condition.light] ?? condition.light}</StatusPill>
              <span>
                {condition.label} — {condition.detail}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {readiness.warningCodes.length > 0 ? (
        <p className="mt-3 text-xs text-muted-foreground">Avertissements : {readiness.warningCodes.join(", ")}</p>
      ) : null}

      <Commands item={item} />
    </Panel>
  );
}

function Commands({ item }: { item: Mt5TerminalView }) {
  const [copied, setCopied] = useState<string | null>(null);
  const copy = (command: string) => {
    void navigator.clipboard?.writeText(command).then(() => setCopied(command));
  };
  return (
    <details className="mt-4 text-sm">
      <summary className="cursor-pointer font-medium">Commandes à copier (non exécutées d&apos;ici)</summary>
      <p className="mt-2 text-xs text-muted-foreground">{COMMAND_PREFIX}…</p>
      <ul className="mt-2 flex flex-col gap-1">
        {commandsFor(item).map(({ label, command }) => (
          <li key={command} className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => copy(command)} aria-label={`Copier : ${label}`}>
              <Copy className="size-3.5" aria-hidden />
            </Button>
            <span>{label} :</span>
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{command}</code>
            {copied === command ? <span className="text-xs text-success">copié</span> : null}
          </li>
        ))}
      </ul>
    </details>
  );
}
