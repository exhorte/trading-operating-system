"use client";

import Link from "next/link";
import { ChevronsUpDown, Settings, UserRound, Wallet } from "lucide-react";
import { cn } from "cn";
import { useCockpit } from "@/lib/realtime/provider";
import { usePersistenceHealth, type PersistenceState } from "@/lib/realtime/use-persistence-health";
import { detectFirm } from "@/lib/accounts/firm";
import { brokerMatchersOf } from "@/lib/accounts/settings";
import { useAccountSettings } from "@/lib/accounts/use-account-settings";
import type { ConnectionState, Environment } from "@/lib/contracts/enums";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type Tone = "profit" | "warning" | "loss" | "info" | "muted";

const DOT: Record<Tone, string> = {
  profit: "bg-profit",
  warning: "bg-warning",
  loss: "bg-loss",
  info: "bg-info",
  muted: "bg-muted-foreground",
};

const ENVIRONMENT: Record<Environment, string> = {
  mock: "MOCK",
  demo: "DÉMO",
  paper: "PAPER",
  live: "LIVE",
};

const HUB: Record<ConnectionState, { label: string; tone: Tone }> = {
  mock: { label: "Simulé", tone: "info" },
  connecting: { label: "Connexion…", tone: "warning" },
  connected: { label: "Connecté", tone: "profit" },
  reconnecting: { label: "Reconnexion…", tone: "warning" },
  stale: { label: "Périmé — plus de battement MT5", tone: "warning" },
  degraded: { label: "Dégradé", tone: "warning" },
  disconnected: { label: "Déconnecté", tone: "loss" },
  error: { label: "Erreur", tone: "loss" },
};

function persistenceLine(state: PersistenceState): { label: string; tone: Tone } {
  switch (state.kind) {
    case "not_applicable":
      return { label: "sans objet (mock)", tone: "muted" };
    case "unknown":
      return { label: "—", tone: "muted" };
    case "ok":
      return { label: "OK", tone: "profit" };
    case "issue":
      return {
        label:
          state.health.dropped > 0 ? `${state.health.dropped} événements perdus` : "base injoignable",
        tone: "loss",
      };
  }
}

/**
 * One dot for "can I trust what I see": the worst of the realtime link and
 * the persistence health. Steel in mock mode — the figures are scripted, and
 * that must stay visible.
 */
function overallTone(connection: ConnectionState, persistence: PersistenceState, environment: Environment): Tone {
  if (connection === "disconnected" || connection === "error" || persistence.kind === "issue") {
    return "loss";
  }
  if (connection === "stale" || connection === "degraded" || connection === "reconnecting" || connection === "connecting") {
    return "warning";
  }
  return environment === "mock" ? "info" : "profit";
}

function StatusRow({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex items-center gap-1.5 text-right text-foreground">
        <span className={cn("size-1.5 shrink-0 rounded-full", DOT[tone])} aria-hidden />
        {value}
      </span>
    </div>
  );
}

/**
 * The only thing left in the top bar, as on the reference mock-up: the
 * account — who, which firm, which environment — with a status dot on the
 * avatar, and behind it the link details (realtime, persistence, EA-05
 * agent) that used to be four pills. Nothing here logs in anywhere: the
 * account is whichever one MT5 has open (ADR 0003).
 */
export function AccountMenu() {
  const { account, connection, environment, executionAgentConnected } = useCockpit();
  const { resolved } = useAccountSettings();
  const persistence = usePersistenceHealth();

  const firm = account ? detectFirm(account.broker, brokerMatchersOf(resolved.settings)) : null;
  const name = !account ? "Aucun compte" : firm === "ftmo" ? "FTMO" : firm === "exness" ? "Exness" : account.broker;
  const env = ENVIRONMENT[environment];
  const subtitle = account ? `${account.accountId} · ${env}` : `MT5 non connecté · ${env}`;
  const initials = firm === "ftmo" ? "FT" : firm === "exness" ? "EX" : null;
  const tone = overallTone(connection, persistence, environment);
  const hub = HUB[connection];
  const store = persistenceLine(persistence);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-3 rounded-xl py-1.5 pr-2 pl-3 text-left transition-colors outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Compte et état de la liaison"
        >
          <span className="hidden min-w-0 sm:block">
            <span className="block truncate text-sm font-medium leading-tight text-foreground">{name}</span>
            <span className="block truncate text-[11px] tracking-wide text-muted-foreground uppercase">{subtitle}</span>
          </span>
          <span className="relative shrink-0">
            <Avatar size="lg" className="ring-1 ring-border">
              <AvatarFallback className="bg-muted text-xs font-semibold text-foreground">
                {initials ?? <UserRound className="size-5 text-muted-foreground" strokeWidth={1.75} />}
              </AvatarFallback>
            </Avatar>
            <span
              className={cn(
                "absolute -right-0.5 -bottom-0.5 size-3 rounded-full ring-2 ring-background",
                DOT[tone],
                tone !== "profit" && tone !== "info" && "animate-pulse",
              )}
              aria-hidden
            />
          </span>
          <ChevronsUpDown className="hidden size-4 text-muted-foreground sm:block" strokeWidth={1.75} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 rounded-xl p-2">
        <DropdownMenuLabel className="flex flex-col gap-0.5 font-normal">
          <span className="text-sm font-medium text-foreground">{name}</span>
          <span className="truncate text-xs text-muted-foreground">
            {account ? `${account.label} · ${account.currency}` : "Ouvre un compte dans MT5 : le cockpit le suit."}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="flex flex-col gap-2 px-2 py-2 text-xs">
          <StatusRow label="Temps réel" value={hub.label} tone={hub.tone} />
          <StatusRow label="Persistance" value={store.label} tone={store.tone} />
          <StatusRow
            label="Agent EA-05"
            value={executionAgentConnected ? "Connecté · observe" : "Non connecté"}
            tone={executionAgentConnected ? "profit" : "muted"}
          />
          <StatusRow label="Environnement" value={env} tone={environment === "live" ? "loss" : environment === "mock" ? "info" : "muted"} />
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild className="gap-2.5 rounded-lg py-2">
          <Link href="/account">
            <Wallet className="size-4" strokeWidth={1.75} />
            Account
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild className="gap-2.5 rounded-lg py-2">
          <Link href="/settings">
            <Settings className="size-4" strokeWidth={1.75} />
            Settings
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
