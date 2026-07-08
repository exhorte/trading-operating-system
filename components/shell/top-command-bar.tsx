"use client";

import { usePathname } from "next/navigation";
import { useCockpit } from "@/lib/realtime/provider";
import type { Environment } from "@/lib/contracts/enums";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { ConnectionBadge } from "./connection-badge";
import { pageTitleFor } from "./nav";

const ENV_BADGE: Record<Environment, { label: string; tone: PillTone }> = {
  mock: { label: "MOCK", tone: "accent" },
  demo: { label: "DEMO", tone: "info" },
  paper: { label: "PAPER", tone: "warning" },
  live: { label: "LIVE", tone: "loss" },
};

export function TopCommandBar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  const pathname = usePathname();
  const { account, environment, marketContext } = useCockpit();
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
        <StatusPill tone={env.tone} pulse>
          {env.label}
        </StatusPill>
        <ConnectionBadge />
        {/* Inert by design: execution controls stay disabled until a real,
            risk-gated execution path exists (quality_gates.md). */}
        <button
          type="button"
          disabled
          title="Disabled: read-only / observe mode, no live execution path yet"
          className="cursor-not-allowed rounded border border-loss/30 px-2 py-1 text-xs text-loss/50"
        >
          Emergency stop
        </button>
      </div>
    </header>
  );
}
