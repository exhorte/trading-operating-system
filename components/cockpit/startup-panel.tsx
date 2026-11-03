"use client";

import { useState } from "react";
import Link from "next/link";
import {
  CircleCheck,
  CircleX,
  ExternalLink,
  Loader2,
  OctagonPause,
  Play,
  Power,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import { cn } from "cn";
import { call } from "@/lib/api/client";
import { useApi } from "@/lib/api/use-api";
import type { AutonomyMode, StartupStatus } from "@/lib/api/generated";
import {
  checkLabel,
  MODE_LABELS,
  MODE_RIGHTS,
  modeTone,
  REAL_ACCOUNT_BANNER,
  runLine,
  START_LABEL,
  STATE_LABELS,
  stateTone,
  STOP_ENTRIES,
  verdictLine,
} from "@/lib/cockpit/startup";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

const POLL_MS = 1500;
const messageOf = (error: unknown): string => (error instanceof Error ? error.message : "Opération impossible.");

/** The core's picture of the start-up, kept fresh. `null` until the first answer. */
function useStartup() {
  return useApi("system_startup_status", {}, { pollMs: POLL_MS });
}

function RealAccountBanner() {
  return (
    <p role="alert" className="rounded-lg bg-destructive px-4 py-2.5 text-sm font-semibold text-destructive-foreground">
      {REAL_ACCOUNT_BANNER}
    </p>
  );
}

// ----------------------------------------------------------------------------------------------------- the start button

/**
 * « DÉMARRER LE SYSTÈME » — starts the trading system: verifies each component, reconciles with MT5, and climbs OFF → OBSERVE. That is
 * all it does: it never goes past CONFIRM, never arms, never sends an order, and a restart never resumes trading by itself. Authorising
 * automatic trading is the separate card on the Démarrage screen.
 */
export function StartSystemButton({ size = "default", className }: { size?: "default" | "sm" | "lg"; className?: string }) {
  const startup = useStartup();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = startup.data;
  const running = status?.run?.state === "RUNNING";
  const alreadyUp = status !== null && status.mode !== "OFF" && !status.halted;

  async function start() {
    setOpen(true);
    if (alreadyUp || running) {
      return; // nothing to start: show where things stand
    }
    setBusy(true);
    setError(null);
    try {
      await call("system_startup_begin", { body: { target: "OBSERVE", acknowledgeRealAccount: false } });
      startup.refresh();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button type="button" size={size} className={cn("font-semibold tracking-wide", className)} onClick={() => void start()} disabled={busy}>
        {busy || running ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Play aria-hidden="true" />}
        {alreadyUp ? "SYSTÈME DÉMARRÉ — VOIR L'ÉTAT" : START_LABEL}
      </Button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>{START_LABEL}</SheetTitle>
            <SheetDescription>
              Vérifie chaque composant, réconcilie avec MT5 et monte jusqu&apos;à OBSERVE. Aucun ordre n&apos;est envoyé.
            </SheetDescription>
          </SheetHeader>
          <div className="flex flex-col gap-4 px-4 pb-6">
            {error && (
              <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                {error}
              </p>
            )}
            {status ? <StatusBody status={status} /> : <Skeleton className="h-64 rounded-xl" />}
            <Button asChild variant="outline" size="sm" className="self-start">
              <Link href="/demarrage" onClick={() => setOpen(false)}>
                <ExternalLink aria-hidden="true" />
                Écran Démarrage : conditions, compte, autorisation
              </Link>
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

// ----------------------------------------------------------------------------------------------------- the pieces

function ModeBlock({ status }: { status: StartupStatus }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill tone={modeTone(status.planMode)} pulse={status.planMode === "HALTED"}>
          {MODE_LABELS[status.planMode]}
        </StatusPill>
        <span className="text-xs text-muted-foreground">plafond du compte : {status.ceiling}</span>
      </div>
      <p className="text-sm text-muted-foreground">{MODE_RIGHTS[status.planMode]}</p>
      <p className={cn("text-sm font-medium", status.entriesAuthorized ? "text-success" : "text-foreground")}>{verdictLine(status)}</p>
      {runLine(status) && (
        <p
          className={cn(
            "text-sm",
            status.run?.state === "BLOCKED" ? "text-destructive" : status.run?.state === "PARTIAL" ? "text-warning" : "text-muted-foreground",
          )}
        >
          {runLine(status)}
        </p>
      )}
    </div>
  );
}

function StageList({ status }: { status: StartupStatus }) {
  return (
    <ol className="flex flex-col divide-y rounded-lg border">
      {status.stages.map((stage) => (
        <li key={stage.stageId} className="flex items-start gap-3 px-3 py-2.5">
          <span className="mt-0.5 w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{stage.order}</span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{stage.label}</p>
            <p className="text-xs leading-snug text-muted-foreground [overflow-wrap:anywhere]">{stage.detail}</p>
          </div>
          <StatusPill tone={stateTone(stage.state)} pulse={stage.state === "STARTING"}>
            {STATE_LABELS[stage.state]}
          </StatusPill>
        </li>
      ))}
    </ol>
  );
}

function ChecksList({ status }: { status: StartupStatus }) {
  const red = status.checks.filter((c) => !c.ok);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        {red.length === 0
          ? "Les 22 conditions sont réunies."
          : `${red.length} condition${red.length > 1 ? "s" : ""} sur ${status.checks.length} non remplie${red.length > 1 ? "s" : ""} — tant que l'une manque, aucune position n'est prise en mode d'ordres.`}
      </p>
      <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {[...red, ...status.checks.filter((c) => c.ok)].map((c) => (
          <li key={c.checkId} className="flex items-start gap-2 text-sm">
            {c.ok ? (
              <CircleCheck className="mt-0.5 size-4 shrink-0 text-success" aria-label="Au vert" />
            ) : (
              <CircleX className="mt-0.5 size-4 shrink-0 text-destructive" aria-label="Bloquant" />
            )}
            <span className="min-w-0">
              <span className={cn(!c.ok && "font-medium")}>{checkLabel(c.checkId, c.label)}</span>
              {!c.ok && <span className="block text-xs text-muted-foreground [overflow-wrap:anywhere]">{c.detail}</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AccountCard({ status }: { status: StartupStatus }) {
  const a = status.account;
  if (!a) {
    return (
      <p className="text-sm text-muted-foreground">
        Aucun compte sélectionné. Enregistrez et connectez un compte dans{" "}
        <Link href="/settings" className="underline underline-offset-4">
          Settings
        </Link>{" "}
        (le mot de passe reste dans MT5 : il ne passe jamais par le cockpit).
      </p>
    );
  }
  const rows: [string, React.ReactNode][] = [
    ["Fournisseur", a.provider],
    ["Serveur MT5", a.server],
    ["Compte sélectionné", `${a.name} · ${a.loginMasked}`],
    ["Type", <StatusPill key="env" tone={a.environment === "LIVE" ? "loss" : "info"}>{a.environment === "LIVE" ? "Réel" : a.environment === "DEMO" ? "Démo" : "Simulé"}</StatusPill>],
    ["Devise", a.currency],
    ["Balance", a.balance === null ? "—" : a.balance.toFixed(2)],
    ["Equity", a.equity === null ? "—" : a.equity.toFixed(2)],
    ["Connexion", <StatusPill key="conn" tone={a.connected ? "profit" : "warning"}>{a.connected ? "Connecté" : a.status}</StatusPill>],
    ["Autorisation de trading", a.tradingEnabled ? "Activée" : "Désactivée par vous"],
    ["Agent MQL5", a.agentConnected ? (a.agentTradable === false ? "Connecté — compte non listé pour trader" : "Connecté") : "Non connecté"],
    ["Terminal : trading autorisé", a.terminalTradeAllowed === null ? "—" : a.terminalTradeAllowed ? "Oui" : "Non"],
    ["Plafond de mode du compte", a.ceiling],
  ];
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-baseline justify-between gap-3 border-b border-dashed pb-1.5">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0 truncate text-right font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Actions({ status, onChanged }: { status: StartupStatus; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<"OBSERVE" | "PAPER" | "CONFIRM">("OBSERVE");
  const [acknowledge, setAcknowledge] = useState(false);
  const running = status.run?.state === "RUNNING";

  async function act(name: string, work: () => Promise<unknown>) {
    setBusy(name);
    setError(null);
    try {
      await work();
      onChanged();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(null);
    }
  }

  const needsAck = status.realAccount && target === "CONFIRM";
  return (
    <div className="flex flex-col gap-3">
      {error && (
        <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm">
          Monter jusqu&apos;à
          <select
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            value={target}
            onChange={(event) => setTarget(event.target.value as typeof target)}
          >
            <option value="OBSERVE">OBSERVE (recommandé)</option>
            <option value="PAPER">PAPER</option>
            <option value="CONFIRM">{status.realAccount ? "LIVE_CONFIRM" : "CONFIRM"}</option>
          </select>
        </label>
        <Button
          type="button"
          disabled={!status.canStart || running || busy !== null || (needsAck && !acknowledge)}
          onClick={() =>
            void act("start", () =>
              call("system_startup_begin", { body: { target: target as AutonomyMode, acknowledgeRealAccount: acknowledge } }),
            )
          }
          className="font-semibold tracking-wide"
        >
          {busy === "start" || running ? <Loader2 className="animate-spin" aria-hidden="true" /> : <Play aria-hidden="true" />}
          {START_LABEL}
        </Button>
      </div>
      {needsAck && (
        <label className="flex cursor-pointer items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5 size-4" checked={acknowledge} onChange={(event) => setAcknowledge(event.target.checked)} />
          <span>Je comprends que ce compte est réel : en LIVE_CONFIRM, un ordre que je confirme engage de l&apos;argent réel.</span>
        </label>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
        {STOP_ENTRIES.map((stop) => (
          <Button
            key={stop.target}
            type="button"
            variant="outline"
            size="sm"
            disabled={busy !== null || status.halted || status.mode === stop.target || status.mode === "OFF"}
            title={stop.hint}
            onClick={() =>
              void act(stop.target, () => call("autonomy_disarm", { body: { target: stop.target, reason: `${stop.label} (cockpit)` } }))
            }
          >
            {stop.target === "OFF" ? <Power aria-hidden="true" /> : <OctagonPause aria-hidden="true" />}
            {stop.label}
          </Button>
        ))}
        {status.halted && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={busy !== null}
            onClick={() => void act("ack", () => call("autonomy_disarm", { body: { acknowledge: true, reason: "halt acknowledged (cockpit)" } }))}
          >
            Acquitter l&apos;arrêt (retour à OFF)
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Trois gestes distincts, jamais fusionnés : arrêter les entrées (OBSERVE), éteindre les moteurs de stratégie (OFF), et — à part —
        fermer toutes les positions. L&apos;arrêt d&apos;urgence (barre latérale) coupe les entrées sans rien fermer.
      </p>
    </div>
  );
}

function AuthorizeCard({ status, onChanged }: { status: StartupStatus; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acknowledge, setAcknowledge] = useState(false);
  const next = status.nextAutomaticMode;
  const live = status.realAccount;
  const nextName = next === null ? null : live ? "LIVE_AUTO" : "DEMO_AUTO";

  async function authorize() {
    setBusy(true);
    setError(null);
    try {
      await call("system_startup_authorize_automatic", { body: { acknowledgeRealAccount: acknowledge } });
      setAcknowledge(false);
      onChanged();
    } catch (failure) {
      setError(messageOf(failure));
    } finally {
      setBusy(false);
    }
  }

  if (next === null) {
    return (
      <p className="text-sm text-muted-foreground">
        Le trading automatique s&apos;autorise depuis {live ? "LIVE_CONFIRM" : "CONFIRM"} (un échelon à la fois). Démarrez d&apos;abord jusqu&apos;à{" "}
        {live ? "LIVE_CONFIRM" : "CONFIRM"}.
        {status.planMode === "DEMO_AUTO" || status.planMode === "LIVE_AUTO" ? ` Mode actuel : ${status.planMode}.` : ""}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {live && <RealAccountBanner />}
      <p className="text-sm text-muted-foreground">
        {next === "ARMED"
          ? `Autorise ${nextName} pour une fenêtre de 30 minutes que vous renouvelez.`
          : `Passe de ${live ? "LIVE_AUTO (fenêtre)" : "DEMO_AUTO (fenêtre)"} à ${nextName} sans fenêtre.`}{" "}
        Exige que les 22 conditions soient vertes à cet instant. Un redémarrage du cœur retombe toujours à OFF.
      </p>
      {status.authorizeBlockers.length > 0 && (
        <p className="flex items-start gap-2 text-sm text-destructive">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          Bloqué par : {status.authorizeBlockers.map((id) => checkLabel(id, id)).join(" · ")}
        </p>
      )}
      {live && (
        <label className="flex cursor-pointer items-start gap-2 text-sm">
          <input type="checkbox" className="mt-0.5 size-4" checked={acknowledge} onChange={(event) => setAcknowledge(event.target.checked)} />
          <span>Je confirme activer le trading automatique sur un compte réel : le système pourra engager de l&apos;argent réel sans mon geste ordre par ordre.</span>
        </label>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button
        type="button"
        variant={live ? "destructive" : "default"}
        className="self-start font-semibold tracking-wide"
        disabled={busy || !status.canAuthorizeAutomatic || (live && !acknowledge)}
        onClick={() => void authorize()}
      >
        {busy && <Loader2 className="animate-spin" aria-hidden="true" />}
        AUTORISER LE TRADING AUTOMATIQUE ({nextName})
      </Button>
    </div>
  );
}

// ----------------------------------------------------------------------------------------------------- compositions

function StatusBody({ status }: { status: StartupStatus }) {
  return (
    <div className="flex flex-col gap-4">
      {status.realAccountBanner && <RealAccountBanner />}
      <ModeBlock status={status} />
      <StageList status={status} />
    </div>
  );
}

/** The whole Démarrage screen: where things stand, what blocks, the account, and the two gestures that move the system. */
export function StartupScreen() {
  const startup = useStartup();
  const status = startup.data;

  if (!status) {
    return startup.error ? (
      <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        {startup.error.message}
      </p>
    ) : (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-40 rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      {status.realAccountBanner && <RealAccountBanner />}
      <Panel title="Où en est le système" description="Treize étapes, chacune vérifiée par le cœur — pas supposée." icon={Play}>
        <div className="flex flex-col gap-4">
          <ModeBlock status={status} />
          <Actions status={status} onChanged={startup.refresh} />
        </div>
      </Panel>
      <Panel title="Étapes du démarrage" description="Application, services, base, terminal, compte, agent, réconciliation, moteurs, mode.">
        <StageList status={status} />
      </Panel>
      <Panel
        title="Conditions avant toute position"
        description="Seize contrôles de préparation du cœur + six propres au démarrage."
        icon={CircleCheck}
      >
        <ChecksList status={status} />
      </Panel>
      <Panel
        title="Compte et connexion"
        description="Détecté depuis le terminal MT5 : aucun identifiant n'est demandé ici ni affiché en entier."
        icon={Wallet}
      >
        <AccountCard status={status} />
      </Panel>
      <Panel
        title="Autoriser le trading automatique"
        description="Un geste séparé du démarrage. Démarrer n'autorise jamais d'ordre automatique."
        icon={ShieldAlert}
      >
        <AuthorizeCard status={status} onChanged={startup.refresh} />
      </Panel>
    </div>
  );
}
