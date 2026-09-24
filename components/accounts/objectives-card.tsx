"use client";

import { useMemo } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { useJournalWindow } from "@/lib/journal/use-journal-window";
import type { ActiveProfile } from "@/lib/accounts/active-profile";
import {
  evaluateFtmoObjectives,
  type ObjectiveRow,
  type ObjectiveState,
} from "@/lib/accounts/objectives";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

/** One FTMO account is one challenge: every closed trade it has belongs to
 *  it, so the window only needs to start before any trade could exist. */
const ACCOUNT_HISTORY_FROM = "2020-01-01";

const OBJECTIVE_PILLS: Record<ObjectiveState, { tone: PillTone; label: string }> = {
  atteint: { tone: "profit", label: "Atteint" },
  en_cours: { tone: "info", label: "En cours" },
  respecte: { tone: "profit", label: "Respecté" },
  depasse: { tone: "loss", label: "Dépassé" },
  non_source: { tone: "muted", label: "Non sourcé" },
};

/** The four MetriX objectives of the connected FTMO challenge (T12). */
export function ObjectivesCard({ profile }: { profile: ActiveProfile }) {
  const { account } = useCockpit();
  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const { trades, failed } = useJournalWindow(
    account?.accountId ?? null,
    ACCOUNT_HISTORY_FROM,
    today,
  );

  const rows: ObjectiveRow[] | null = useMemo(() => {
    if (!account || !profile.challenge || !trades) {
      return null;
    }
    return evaluateFtmoObjectives({
      challenge: profile.challenge,
      policy: profile.riskPolicy,
      trades,
      balance: account.balance,
      equity: account.equity,
    });
  }, [account, profile, trades]);

  if (failed) {
    return (
      <Card title="Objectifs du challenge">
        <p className="text-xs text-muted">
          Les trades clôturés n&apos;ont pas pu être chargés — sans eux, ni les jours de trading
          ni la pire journée ne se calculent. Le backend répond-il ?
        </p>
      </Card>
    );
  }

  if (!rows) {
    return (
      <Card title="Objectifs du challenge">
        <Skeleton className="h-44" />
      </Card>
    );
  }

  return (
    <Card
      title="Objectifs du challenge"
      actions={<span className="text-[11px] text-muted">{trades?.length ?? 0} trade(s) clôturé(s)</span>}
    >
      <ul className="flex flex-col">
        {rows.map((row) => {
          const pill = OBJECTIVE_PILLS[row.state];
          return (
            <li key={row.key} className="border-t border-border py-2 first:border-t-0 first:pt-0">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="text-foreground">{row.label}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="tnum text-muted">{row.result}</span>
                  <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
                </span>
              </div>
              <p className="mt-1 text-[11px] leading-snug text-muted">{row.note}</p>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
