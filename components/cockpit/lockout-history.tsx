"use client";

import { useComplianceRate } from "@/lib/compliance/use-compliance-rate";
import type { LockoutWindow } from "@/lib/compliance/violations";
import { Card } from "@/components/ui/card";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

function formatStamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatSpan(since: string, endIso: string | null): string {
  const end = endIso === null ? Date.now() : Date.parse(endIso);
  const minutes = Math.max(0, Math.round((end - Date.parse(since)) / 60_000));
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest.toString().padStart(2, "0")}`;
}

function stateOf(lockout: LockoutWindow): { label: string; tone: PillTone } {
  if (lockout.clearedAt === null) {
    return { label: "actif", tone: "loss" };
  }
  return lockout.until === null
    ? { label: "acquitté", tone: "muted" }
    : { label: "expiré", tone: "muted" };
}

/**
 * Every lockout this account has ever carried, newest first.
 *
 * The data has been served by GET /api/risk/lockouts since T07 and had no
 * screen: it was read only by the compliance detectors, never shown as a
 * history. It is the trace of the two Vague 1 incidents (six trades opened
 * while a lock was held, 2026-09-14 and 2026-09-15) and of the acknowledgment
 * cycle T02c made mandatory — the kind of thing a personal risk system exists
 * to keep in front of the trader.
 *
 * Reuses the fetch already made by the discipline gauge: the endpoint returns
 * the full history regardless of window ("a personal system has a handful of
 * lockouts, ever" — RiskLockoutHistoryRepository), so there is nothing extra
 * to ask for.
 */
export function LockoutHistory() {
  const { lockouts, rate } = useComplianceRate();

  const ordered = [...lockouts].sort((a, b) => Date.parse(b.since) - Date.parse(a.since));
  const openCount = ordered.filter((l) => l.clearedAt === null).length;

  if (rate === null) {
    return (
      <Card title="Historique des verrous">
        <p className="text-xs text-muted">Chargement…</p>
      </Card>
    );
  }

  return (
    <Card
      title="Historique des verrous"
      actions={
        openCount > 0 ? (
          <StatusPill tone="loss" pulse>
            {openCount} non levé(s)
          </StatusPill>
        ) : (
          <span className="text-[11px] text-muted">{ordered.length} au total</span>
        )
      }
    >
      {ordered.length === 0 ? (
        <p className="text-xs text-muted">
          Aucun verrou enregistré pour ce compte. Un historique vide veut dire qu&apos;aucune
          limite n&apos;a jamais été atteinte — pas que les limites sont inactives.
        </p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase tracking-wider text-muted">
              <th className="pb-1 font-medium">Motif</th>
              <th className="pb-1 font-medium">Déclenché</th>
              <th className="pb-1 font-medium">Levé</th>
              <th className="pb-1 text-right font-medium">Durée</th>
              <th className="pb-1 text-right font-medium">État</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((lockout) => {
              const state = stateOf(lockout);
              return (
                <tr key={lockout.lockoutId} className="border-t border-border">
                  <td className="py-1.5 text-foreground">{lockout.reason}</td>
                  <td className="tnum py-1.5 text-muted">{formatStamp(lockout.since)}</td>
                  <td className="tnum py-1.5 text-muted">
                    {lockout.clearedAt === null ? "—" : formatStamp(lockout.clearedAt)}
                  </td>
                  <td className="tnum py-1.5 text-right text-muted">
                    {formatSpan(lockout.since, lockout.clearedAt)}
                  </td>
                  <td className="py-1.5 text-right">
                    <StatusPill tone={state.tone}>{state.label}</StatusPill>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}
