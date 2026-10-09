"use client";

import { History } from "lucide-react";
import { useComplianceRate } from "@/lib/compliance/use-compliance-rate";
import type { LockoutWindow } from "@/lib/api/generated";
import { SectionHeading } from "@/components/shell/page-header";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
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

const StateBadge = ({ lockout }: { lockout: LockoutWindow }) => {
  const state = stateOf(lockout);
  return <StatusPill tone={state.tone}>{state.label}</StatusPill>;
};

const COLUMNS: Column<LockoutWindow>[] = [
  { key: "reason", header: "Motif", cell: (l) => <span className="font-medium">{l.reason}</span> },
  { key: "since", header: "Déclenché", cell: (l) => <span className="text-muted-foreground">{formatStamp(l.since)}</span> },
  {
    key: "cleared",
    header: "Levé",
    cell: (l) => <span className="text-muted-foreground">{l.clearedAt === null ? "—" : formatStamp(l.clearedAt)}</span>,
  },
  {
    key: "span",
    header: "Durée",
    align: "right",
    cell: (l) => <span className="text-muted-foreground">{formatSpan(l.since, l.clearedAt)}</span>,
  },
  { key: "state", header: "État", align: "right", cell: (l) => <StateBadge lockout={l} /> },
];

/**
 * Every lockout this account has ever carried, newest first.
 *
 * The data is the core's lockout ledger (GET /api/risk/lockouts). It is the
 * trace of the two Vague 1 incidents (six trades opened while a lock was held,
 * 2026-09-14 and 2026-09-15) and of the acknowledgment cycle T02c made
 * mandatory — the kind of thing a personal risk system exists to keep in front
 * of the trader.
 *
 * Reads through the same hook as the discipline gauge: the ledger is the full
 * history regardless of window ("a personal system has a handful of lockouts,
 * ever"), so there is nothing extra to ask for.
 */
export function LockoutHistory() {
  const { lockouts, rate, failed } = useComplianceRate();

  const ordered = [...lockouts].sort((a, b) => Date.parse(b.since) - Date.parse(a.since));
  const openCount = ordered.filter((l) => l.clearedAt === null).length;

  const heading = (actions?: React.ReactNode) => (
    <SectionHeading
      title="Historique des verrous"
      subtitle="chaque limite atteinte, et ce qui l'a levée"
      icon={History}
      actions={actions}
    />
  );

  if (rate === null) {
    return (
      <section className="flex flex-col gap-4">
        {heading()}
        <p className="rounded-xl border border-dashed py-8 text-center text-sm text-muted-foreground">
          {failed ? "Historique illisible — le cœur répond-il ?" : "Chargement…"}
        </p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-4">
      {heading(
        openCount > 0 ? (
          <StatusPill tone="loss" pulse>
            {openCount} non levé(s)
          </StatusPill>
        ) : (
          <span className="text-sm text-muted-foreground">{ordered.length} au total</span>
        ),
      )}
      {ordered.length === 0 ? (
        <p className="rounded-xl border border-dashed px-6 py-8 text-center text-sm text-muted-foreground">
          Aucun verrou enregistré pour ce compte. Un historique vide veut dire qu&apos;aucune limite n&apos;a jamais été
          atteinte — pas que les limites sont inactives.
        </p>
      ) : (
        <DataList
          rows={ordered}
          columns={COLUMNS}
          rowKey={(l) => l.lockoutId}
          mobileCard={(l) => (
            <>
              <MobileCardHeader name={l.reason} subtitle={formatStamp(l.since)} badge={<StateBadge lockout={l} />} />
              <MobileFields
                fields={[
                  { label: "Levé", value: l.clearedAt === null ? "—" : formatStamp(l.clearedAt) },
                  { label: "Durée", value: formatSpan(l.since, l.clearedAt) },
                ]}
              />
            </>
          )}
        />
      )}
    </section>
  );
}
