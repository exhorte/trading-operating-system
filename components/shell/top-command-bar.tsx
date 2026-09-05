"use client";

import { usePathname } from "next/navigation";
import { useCockpit, useTriggerKillSwitch } from "@/lib/realtime/provider";
import type { Environment } from "@/lib/contracts/enums";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { ConnectionBadge } from "./connection-badge";
import { NewsCalendarBadge } from "./news-calendar-badge";
import { PersistenceHealthBadge } from "./persistence-health-badge";
import { pageTitleFor } from "./nav";

const ENV_BADGE: Record<Environment, { label: string; tone: PillTone }> = {
  mock: { label: "MOCK", tone: "accent" },
  demo: { label: "DEMO", tone: "info" },
  paper: { label: "PAPER", tone: "warning" },
  live: { label: "LIVE", tone: "loss" },
};

export function TopCommandBar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  const pathname = usePathname();
  const { account, environment, marketContext, activeLockout } = useCockpit();
  const triggerKillSwitch = useTriggerKillSwitch();
  const env = ENV_BADGE[environment];

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-surface px-3">
      <button
        type="button"
        onClick={onToggleSidebar}
        className="rounded border border-border px-2 py-1 text-xs text-muted hover:text-foreground"
        aria-label="Toggle navigation sidebar"
      >
        ☰
      </button>
      <h1 className="text-sm font-semibold">{pageTitleFor(pathname)}</h1>

      <div className="ml-auto flex items-center gap-2">
        <span className="hidden rounded border border-border bg-surface-elevated px-2 py-1 text-xs text-muted md:inline">
          {account ? account.label : "No account"}
        </span>
        <span className="hidden rounded border border-border bg-surface-elevated px-2 py-1 text-xs text-muted sm:inline">
          {marketContext?.symbol ?? "XAUUSD"}
        </span>
        <NewsCalendarBadge />
        <StatusPill tone={env.tone} pulse>
          {env.label}
        </StatusPill>
        <ConnectionBadge />
        <PersistenceHealthBadge />
        {/* T02a: real now — locks the account for real (persisted ledger).
            Still never touches the broker: no close_all command exists, so
            closing positions stays a manual MT5 action (KillSwitchBanner). */}
        <button
          type="button"
          disabled={activeLockout !== null}
          onClick={triggerKillSwitch}
          title={
            activeLockout !== null
              ? "Déjà verrouillé"
              : "Verrouille le compte immédiatement — les positions restent à fermer dans MT5"
          }
          className="rounded border border-loss/50 px-2 py-1 text-xs text-loss hover:bg-loss/10 disabled:cursor-not-allowed disabled:border-loss/20 disabled:text-loss/40 disabled:hover:bg-transparent"
        >
          Emergency stop
        </button>
      </div>
    </header>
  );
}
