"use client";

import Link from "next/link";
import { ChevronsUpDown, Settings, UserRound, Wallet } from "lucide-react";
import { cn } from "cn";
import { useCockpit } from "@/lib/realtime/provider";
import type { ConnectionState } from "@/lib/realtime/store";
import { usePersistenceHealth, type PersistenceState } from "@/lib/realtime/use-persistence-health";
import type { Environment, Provider } from "@/lib/api/generated";
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
  DEMO: "DÉMO",
  SIMULATED: "SIMULÉ",
  LIVE: "LIVE",
};

const PROVIDER: Record<Provider, { name: string; initials: string }> = {
  FTMO: { name: "FTMO", initials: "FT" },
  EXNESS: { name: "Exness", initials: "EX" },
};

const LINK: Record<ConnectionState, { label: string; tone: Tone }> = {
  connecting: { label: "Connexion…", tone: "warning" },
  connected: { label: "Connecté", tone: "profit" },
  reconnecting: { label: "Reconnexion…", tone: "warning" },
  stale: { label: "Périmé — plus de battement du cœur", tone: "warning" },
  degraded: { label: "Dégradé — le cœur signale un défaut", tone: "warning" },
  disconnected: { label: "Déconnecté", tone: "loss" },
};

function persistenceLine(state: PersistenceState): { label: string; tone: Tone } {
  switch (state.kind) {
    case "unknown":
      return { label: "—", tone: "muted" };
    case "ok":
      return { label: "OK", tone: "profit" };
    case "issue":
      return { label: state.label, tone: "loss" };
  }
}

/**
 * One dot for "can I trust what I see": the worst of the link to the core and
 * its persistence health. Steel on a simulated terminal — the figures are
 * scripted, and that must stay visible.
 */
function overallTone(
  connection: ConnectionState,
  persistence: PersistenceState,
  environment: Environment | null,
): Tone {
  if (connection === "disconnected" || persistence.kind === "issue") {
    return "loss";
  }
  if (connection === "stale" || connection === "degraded" || connection === "reconnecting" || connection === "connecting") {
    return "warning";
  }
  return environment === "SIMULATED" ? "info" : "profit";
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
 * avatar, and behind it the link details (the core, persistence, the EA-05
 * agent) that used to be four pills. Nothing here logs in anywhere: the
 * account is the one the core has attached and made active.
 */
export function AccountMenu() {
  const { registered, account, connection, connectionIssue, environment, executionAgentConnected, agent } =
    useCockpit();
  const persistence = usePersistenceHealth();

  const firm = registered ? PROVIDER[registered.provider] : null;
  const name = !registered ? "Aucun compte" : (firm?.name ?? registered.name);
  const env = environment === null ? "—" : ENVIRONMENT[environment];
  const subtitle = !registered
    ? "Aucun compte actif"
    : account
      ? `${registered.login} · ${env}`
      : `${registered.login} · non connecté · ${env}`;
  const initials = firm?.initials ?? null;
  const tone = overallTone(connection, persistence, environment);
  const link = LINK[connection];
  const store = persistenceLine(persistence);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-3 rounded-lg py-1.5 pr-2 pl-3 text-left transition-colors outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/40"
          aria-label="Compte et état de la liaison"
        >
          <span className="hidden min-w-0 sm:block">
            <span className="block truncate text-sm font-medium leading-tight text-foreground">{name}</span>
            <span className="block truncate text-[0.6875rem] tracking-wide text-muted-foreground uppercase">{subtitle}</span>
          </span>
          <span className="relative shrink-0">
            <Avatar size="lg" className="ring-1 ring-border">
              <AvatarFallback className="bg-muted text-xs font-semibold text-foreground">
                {initials ?? <UserRound className="size-5 text-muted-foreground" aria-hidden="true" />}
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
      <DropdownMenuContent align="end" className="w-80 rounded-lg p-2">
        <DropdownMenuLabel className="flex flex-col gap-0.5 font-normal">
          <span className="text-sm font-medium text-foreground">{name}</span>
          <span className="truncate text-xs text-muted-foreground">
            {account
              ? `${account.label} · ${account.currency}`
              : registered
                ? `${registered.name} — rattache-le dans Account`
                : "Enregistre un compte dans Settings, puis rattache-le."}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <div className="flex flex-col gap-2 px-2 py-2 text-xs">
          <StatusRow label="Cœur" value={link.label} tone={link.tone} />
          {connectionIssue && connection !== "connected" ? (
            <p className="text-[0.6875rem] leading-snug text-warning">{connectionIssue}</p>
          ) : null}
          <StatusRow label="Persistance" value={store.label} tone={store.tone} />
          <StatusRow
            label="Agent EA-05"
            value={executionAgentConnected ? `Connecté · ${agent?.mode ?? "?"}` : "Non connecté"}
            tone={executionAgentConnected ? "profit" : "muted"}
          />
          <StatusRow
            label="Environnement"
            value={env}
            tone={environment === "LIVE" ? "loss" : environment === "SIMULATED" ? "info" : "muted"}
          />
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
