"use client";

import { useMemo, useState } from "react";
import type { SignalStatus } from "@/lib/contracts/enums";
import type {
  ExecutionReport,
  RiskDecisionView,
  StrategySignal,
} from "@/lib/contracts/snapshots";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const STATUS_TONES: Record<SignalStatus, PillTone> = {
  detected: "info",
  scored: "info",
  risk_review: "warning",
  approved: "profit",
  rejected: "loss",
  commanded: "accent",
  acknowledged: "accent",
  reported: "muted",
  expired: "muted",
};

/** Happy-path lifecycle; rejected/expired are terminal branches off risk_review. */
const LIFECYCLE: SignalStatus[] = [
  "detected",
  "scored",
  "risk_review",
  "approved",
  "commanded",
  "reported",
];

function price(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fillsFor(signalId: string, reports: ExecutionReport[]): ExecutionReport[] {
  return reports.filter(
    (r) => r.commandId === `cmd-${signalId}` || r.correlationId === `corr-${signalId}`,
  );
}

function Lifecycle({ status }: { status: SignalStatus }) {
  const reached = LIFECYCLE.indexOf(status);
  const terminal = status === "rejected" || status === "expired";
  const reachedTo = reached >= 0 ? reached : 2; // rejected/expired got through risk_review
  return (
    <div className="flex flex-wrap items-center gap-1">
      {LIFECYCLE.map((stage, i) => {
        const done = i <= reachedTo && !(terminal && i > 2);
        const current = i === reached;
        return (
          <span
            key={stage}
            className={`rounded px-1.5 py-0.5 text-[10px] ${
              current
                ? "bg-info/20 text-info"
                : done
                  ? "bg-profit/10 text-profit"
                  : "bg-surface-elevated text-muted"
            }`}
          >
            {stage}
          </span>
        );
      })}
      {terminal && (
        <span className="rounded bg-loss/15 px-1.5 py-0.5 text-[10px] text-loss">{status}</span>
      )}
    </div>
  );
}

function LevelTile({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-border bg-surface-elevated px-2 py-1.5">
      <p className="text-[10px] uppercase tracking-wider text-muted">{label}</p>
      <p className={`tnum text-sm font-semibold ${tone ?? "text-foreground"}`}>{value}</p>
    </div>
  );
}

function GateRow({ gate }: { gate: RiskDecisionView["gates"][number] }) {
  return (
    <li className="flex items-center justify-between gap-2 text-[11px]">
      <span className="flex items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            gate.state === "open" ? "bg-profit" : "bg-warning"
          }`}
          aria-hidden
        />
        {gate.label}
      </span>
      <span className="text-muted">{gate.detail}</span>
    </li>
  );
}

function SignalDetail({
  signal,
  decision,
  fills,
}: {
  signal: StrategySignal;
  decision: RiskDecisionView | undefined;
  fills: ExecutionReport[];
}) {
  const stopTone = "text-loss";
  const targetTone = "text-profit";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold">
            <span className="tnum text-muted">{signal.signalId}</span>
            {signal.symbol}
            <span className={signal.side === "buy" ? "text-profit" : "text-loss"}>
              {signal.side.toUpperCase()}
            </span>
          </div>
          <p className="mt-0.5 text-[11px] text-muted">
            {signal.strategyId} · score{" "}
            <span className="tnum text-foreground">
              {signal.score}/{signal.maxScore}
            </span>{" "}
            · {formatClockTime(signal.createdAt)}
          </p>
        </div>
        <StatusPill tone={STATUS_TONES[signal.status]}>{signal.status}</StatusPill>
      </div>

      <Lifecycle status={signal.status} />

      <div>
        <p className="mb-1 text-[10px] uppercase tracking-wider text-muted">Context</p>
        <p className="text-xs">{signal.contextSummary}</p>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <LevelTile label="Entry" value={price(signal.entryPrice)} />
        <LevelTile label="Stop" value={price(signal.stopLoss)} tone={stopTone} />
        <LevelTile label="Target" value={price(signal.takeProfit)} tone={targetTone} />
      </div>

      <div className="rounded border border-border p-2">
        <div className="mb-1 flex items-center justify-between">
          <p className="text-[10px] uppercase tracking-wider text-muted">Risk decision</p>
          {decision && (
            <StatusPill tone={decision.approved ? "profit" : "loss"}>
              {decision.approved ? "approved" : "rejected"}
            </StatusPill>
          )}
        </div>
        {decision ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted">Approved volume</span>
              <span className="tnum">
                {decision.approvedVolume === null ? "—" : `${decision.approvedVolume} lot`}
              </span>
            </div>
            <p className="text-[11px] text-muted">{decision.reason}</p>
            {decision.gates.length > 0 && (
              <ul className="mt-1 flex flex-col gap-1 border-t border-border pt-1.5">
                {decision.gates.map((gate) => (
                  <GateRow key={gate.gateId} gate={gate} />
                ))}
              </ul>
            )}
          </div>
        ) : (
          <p className="text-[11px] text-muted">
            {signal.status === "risk_review"
              ? "Awaiting risk review…"
              : "No structured decision record for this signal."}
          </p>
        )}
      </div>

      <div className="rounded border border-border p-2">
        <p className="mb-1 text-[10px] uppercase tracking-wider text-muted">Execution</p>
        {fills.length === 0 ? (
          <p className="text-[11px] text-muted">No fill.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {fills.map((report) => (
              <li key={report.reportId} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="flex items-center gap-1.5">
                  <StatusPill tone="muted">{report.status}</StatusPill>
                  {report.detail}
                </span>
                <span className="text-muted">{formatClockTime(report.reportedAt)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function SignalsWorkspace() {
  const { signals, riskDecisions, executionReports } = useCockpit();
  const untrusted = useIsDataUntrusted();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const ordered = useMemo(
    () =>
      [...signals].sort(
        (a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt),
      ),
    [signals],
  );

  const selected =
    ordered.find((s) => s.signalId === selectedId) ?? ordered[0] ?? null;

  if (ordered.length === 0) {
    return (
      <EmptyState
        title="No signals yet"
        description="The mock strategy emits a signal roughly every 15s and runs it through the real risk engine. Switch the realtime source to mock to see the flow; live/observe has no strategy engine."
        hint="Signal → Risk Review → RiskDecision → fill"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-[320px_1fr]">
      <Card title={`Signals (${ordered.length})`} untrusted={untrusted}>
        <ul className="flex flex-col gap-1">
          {ordered.map((signal) => {
            const active = selected?.signalId === signal.signalId;
            return (
              <li key={signal.signalId}>
                <button
                  type="button"
                  onClick={() => setSelectedId(signal.signalId)}
                  className={`w-full rounded border px-2 py-1.5 text-left ${
                    active
                      ? "border-accent/50 bg-accent/10"
                      : "border-border bg-surface-elevated hover:border-border-strong"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="flex items-center gap-1.5 font-medium">
                      <span className="tnum text-muted">{signal.signalId}</span>
                      <span className={signal.side === "buy" ? "text-profit" : "text-loss"}>
                        {signal.side.toUpperCase()}
                      </span>
                    </span>
                    <StatusPill tone={STATUS_TONES[signal.status]}>{signal.status}</StatusPill>
                  </div>
                  <div className="mt-0.5 flex items-center justify-between text-[10px] text-muted">
                    <span className="tnum">
                      score {signal.score}/{signal.maxScore}
                    </span>
                    <span>{formatClockTime(signal.createdAt)}</span>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card title="Signal audit" untrusted={untrusted}>
        {selected ? (
          <SignalDetail
            signal={selected}
            decision={riskDecisions[selected.signalId]}
            fills={fillsFor(selected.signalId, executionReports)}
          />
        ) : (
          <p className="text-xs text-muted">Select a signal.</p>
        )}
      </Card>
    </div>
  );
}
