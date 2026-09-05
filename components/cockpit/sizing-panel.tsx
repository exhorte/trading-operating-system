"use client";

import { useMemo, useState, type ChangeEvent } from "react";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { computeSizingPanel } from "@/lib/risk/sizing-panel";
import { formatMoney, formatPercent } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function parseInput(value: string): number | null {
  if (value.trim() === "") {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <input
        type="number"
        inputMode="decimal"
        step="0.01"
        value={value}
        onChange={onChange}
        className="tnum rounded border border-border bg-surface-elevated px-2 py-1 text-sm text-foreground outline-none focus:border-accent"
      />
    </label>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between text-xs">
      <span className="text-muted">{label}</span>
      <span className="tnum text-foreground">{value}</span>
    </div>
  );
}

/** null means "unknown", never "zero" (dépôt-wide convention) — render "—", not 0%. */
function formatPercentOrUnknown(value: number | null): string {
  return value === null ? "—" : formatPercent(value);
}

/**
 * T01 — permanent, one-click position-sizing panel. Calls the existing pure
 * risk engine (lib/risk) for every number; never modifies it, never sends an
 * order. XAUUSD only (context/product/tools/T01-calculateur-taille.md).
 */
export function SizingPanel() {
  const { account, risk } = useCockpit();
  const untrusted = useIsDataUntrusted();
  const [entryPrice, setEntryPrice] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");

  const result = useMemo(() => {
    if (!account || !risk) {
      return null;
    }
    const entry = parseInput(entryPrice);
    const stop = parseInput(stopLoss);
    if (entry === null || stop === null) {
      return null;
    }
    return computeSizingPanel({
      entryPrice: entry,
      stopLoss: stop,
      takeProfit: parseInput(takeProfit),
      account,
      risk,
      now: new Date().toISOString(),
    });
  }, [account, risk, entryPrice, stopLoss, takeProfit]);

  if (!account || !risk) {
    return (
      <Card title="Sizing — XAUUSD">
        <Skeleton className="h-64" />
      </Card>
    );
  }

  return (
    <Card title="Sizing — XAUUSD" untrusted={untrusted}>
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            label="Entrée"
            value={entryPrice}
            onChange={(e) => setEntryPrice(e.target.value)}
          />
          <NumberField
            label="Stop"
            value={stopLoss}
            onChange={(e) => setStopLoss(e.target.value)}
          />
        </div>
        <NumberField
          label="Take-profit (optionnel)"
          value={takeProfit}
          onChange={(e) => setTakeProfit(e.target.value)}
        />

        {!result && (
          <p className="text-xs text-muted">
            Saisis un prix d&rsquo;entrée et un stop pour calculer la taille.
          </p>
        )}

        {result && result.stopDistance === null && (
          <p className="rounded border border-loss/40 bg-loss/10 px-2 py-1 text-xs text-loss">
            Le stop doit être différent du prix d&rsquo;entrée.
          </p>
        )}

        {result && result.stopDistance !== null && (
          <div className="flex flex-col gap-2 border-t border-border pt-2">
            <Row
              label="Distance au stop"
              value={`${result.stopDistancePoints!.toFixed(0)} pts / ${result.stopDistancePips!.toFixed(1)} pips`}
            />
            {result.takeProfitInvalid && (
              <p className="rounded border border-loss/40 bg-loss/10 px-2 py-1 text-xs text-loss">
                Take-profit du mauvais côté de l&rsquo;entrée pour ce sens de trade.
              </p>
            )}
            {result.rMultipleTarget !== null && (
              <Row label="R cible" value={`${result.rMultipleTarget.toFixed(2)}R`} />
            )}

            {result.decision?.approved && result.decision.approvedVolume !== null ? (
              <>
                <div className="flex items-baseline justify-between">
                  <span className="text-xs text-muted">Volume</span>
                  <span className="tnum text-lg font-semibold text-foreground">
                    {result.decision.approvedVolume} lot
                  </span>
                </div>
                {result.floorApplied && (
                  <p className="rounded border border-warning/40 bg-warning/10 px-2 py-1 text-xs text-warning">
                    Plancher 0.01 lot appliqué — risque réel {formatMoney(result.realRiskUsd!)} au
                    lieu de {formatMoney(result.targetRiskUsd!)} visé.
                  </p>
                )}
                <Row
                  label="Risque visé"
                  value={`${formatMoney(result.targetRiskUsd!)} (${result.policy.maxRiskPerTradePercent}%)`}
                />
                <Row
                  label="Risque réel"
                  value={`${formatMoney(result.realRiskUsd!)} (${formatPercent(result.realRiskPercent!)})`}
                />
                <Row
                  label="Budget perte quotidien restant, consommé"
                  value={formatPercentOrUnknown(result.dailyBudgetConsumedPercent)}
                />
              </>
            ) : (
              <p className="rounded border border-loss/40 bg-loss/10 px-2 py-1 text-xs text-loss">
                {result.decision?.reason}
              </p>
            )}
          </div>
        )}

        <ul className="flex flex-col gap-1 border-t border-border pt-2">
          {risk.gates.map((gate) => (
            <li key={gate.gateId} className="flex items-center justify-between gap-2 text-xs">
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
          ))}
        </ul>
      </div>
    </Card>
  );
}
