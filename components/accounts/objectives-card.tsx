"use client";

import { useMemo } from "react";
import { Trophy } from "lucide-react";
import { useCockpit } from "@/lib/realtime/provider";
import { useJournalWindow } from "@/lib/journal/use-journal-window";
import type { AccountProfile } from "@/lib/accounts/profile";
import {
  evaluateFtmoObjectives,
  type ObjectiveRow,
  type ObjectiveState,
} from "@/lib/accounts/objectives";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

/** One FTMO account is one challenge: every closed trade it has belongs to it, so the window only needs to start before any
 *  trade could exist. The core answers for at most a year; a challenge and its verification last a few months. */
const HISTORY_DAYS = 365;

const OBJECTIVE_PILLS: Record<ObjectiveState, { tone: PillTone; label: string }> = {
  atteint: { tone: "profit", label: "Atteint" },
  en_cours: { tone: "info", label: "En cours" },
  respecte: { tone: "profit", label: "Respecté" },
  depasse: { tone: "loss", label: "Dépassé" },
  non_source: { tone: "muted", label: "Non sourcé" },
};

/** The four MetriX objectives of the connected FTMO challenge (T12). */
export function ObjectivesCard({ profile }: { profile: AccountProfile }) {
  const { account, activeAccountId } = useCockpit();
  const { from, today } = useMemo(() => {
    const now = new Date();
    return {
      today: now.toISOString().slice(0, 10),
      from: new Date(now.getTime() - HISTORY_DAYS * 24 * 60 * 60 * 1000).toISOString().slice(0, 10),
    };
  }, []);
  const { trades, failed } = useJournalWindow(activeAccountId, from, today, { trades: true });

  const rows: ObjectiveRow[] | null = useMemo(() => {
    if (!account || !profile.challenge || !trades) {
      return null;
    }
    return evaluateFtmoObjectives({
      challenge: profile.challenge,
      rules: profile.rules,
      trades,
      balance: account.balance,
      equity: account.equity,
    });
  }, [account, profile, trades]);

  if (failed) {
    return (
      <Panel title="Objectifs du challenge" icon={Trophy}>
        <p className="text-sm text-muted-foreground">
          Les trades clôturés n&apos;ont pas pu être chargés — sans eux, ni les jours de trading
          ni la pire journée ne se calculent. Le cœur répond-il ?
        </p>
      </Panel>
    );
  }

  if (!rows) {
    return (
      <Panel title="Objectifs du challenge" icon={Trophy}>
        <Skeleton className="h-44" />
      </Panel>
    );
  }

  return (
    <Panel
      title="Objectifs du challenge"
      icon={Trophy}
      actions={<span className="text-sm text-muted-foreground">{trades?.length ?? 0} trade(s) clôturé(s)</span>}
    >
      <ul className="flex flex-col">
        {rows.map((row) => {
          const pill = OBJECTIVE_PILLS[row.state];
          return (
            <li key={row.key} className="border-t py-3 first:border-t-0 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-sm">
                <span className="text-foreground">{row.label}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="tnum text-muted-foreground">{row.result}</span>
                  <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
                </span>
              </div>
              <p className="mt-1 text-sm leading-snug text-muted-foreground">{row.note}</p>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
