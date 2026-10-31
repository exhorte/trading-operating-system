"use client";

import { Landmark } from "lucide-react";
import type { Account, AccountStatus, Environment } from "@/lib/api/generated";
import { ACCOUNT_TYPE_LABELS, PROVIDER_NAMES } from "@/lib/accounts/profile";
import { Panel } from "@/components/ui/panel";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { formatDateTime, primaryButtonClass, secondaryButtonClass } from "./form-controls";
import { useAccountActions } from "./use-account-actions";

const STATUS: Record<AccountStatus, { tone: PillTone; label: string }> = {
  CONNECTED: { tone: "profit", label: "Rattaché" },
  CONNECTING: { tone: "warning", label: "Connexion…" },
  ERROR: { tone: "loss", label: "En erreur" },
  DISCONNECTED: { tone: "muted", label: "Détaché" },
};

const ENVIRONMENT: Record<Environment, { tone: PillTone; label: string }> = {
  DEMO: { tone: "info", label: "Démo" },
  SIMULATED: { tone: "info", label: "Simulé" },
  LIVE: { tone: "warning", label: "Réel" },
};

/**
 * One registered account — whether or not it is the one the core is attached to and trading with. Attaching asks the core to
 * read the terminal that is already logged into this account; it never logs in anywhere and no password is asked here. The
 * core refuses what could hide risk (detaching with a position open, switching away from an account that is trading) and
 * says why.
 */
export function RegisteredAccountCard({ account, active }: { account: Account; active: boolean }) {
  const actions = useAccountActions(account.id);
  const busy = actions.state.status === "busy";
  const status = STATUS[account.status];
  const environment = ENVIRONMENT[account.environment];

  return (
    <Panel
      title={`${PROVIDER_NAMES[account.provider]} · ${account.name}`}
      icon={Landmark}
      actions={
        <span className="flex flex-wrap items-center justify-end gap-1.5">
          {active && <StatusPill tone="accent">Actif</StatusPill>}
          <StatusPill tone={status.tone} pulse={account.status === "CONNECTING"}>
            {status.label}
          </StatusPill>
        </span>
      }
    >
      <p className="text-sm text-muted-foreground">
        {ACCOUNT_TYPE_LABELS[account.accountType]} · <span className="tnum">{account.login}</span> · {account.server} ·{" "}
        {account.currency}
      </p>

      <dl className="mt-4 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground">Environnement</dt>
        <dd className="text-right">
          <StatusPill tone={environment.tone}>{environment.label}</StatusPill>
        </dd>
        <dt className="text-muted-foreground">Trading</dt>
        <dd className={`text-right ${account.tradingEnabled ? "text-foreground" : "text-warning"}`}>
          {account.tradingEnabled ? "activé" : "désactivé par toi"}
        </dd>
        <dt className="text-muted-foreground">Suffixe des symboles</dt>
        <dd className="tnum text-right text-foreground">{account.symbolSuffix || "aucun"}</dd>
        <dt className="text-muted-foreground">Terminal</dt>
        <dd className="min-w-0 truncate text-right text-foreground" title={account.terminalPath ?? undefined}>
          {account.terminalPath ?? "celui qui est ouvert"}
        </dd>
        <dt className="text-muted-foreground">Enregistré le</dt>
        <dd className="text-right text-foreground">{formatDateTime(account.createdAt)}</dd>
      </dl>

      {account.statusDetail && (
        <p className="mt-3 text-sm text-destructive" role="status">
          {account.statusDetail}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4">
        {account.status === "CONNECTED" ? (
          <button type="button" disabled={busy} onClick={() => void actions.disconnect()} className={secondaryButtonClass}>
            Détacher
          </button>
        ) : (
          <button
            type="button"
            disabled={busy || account.status === "CONNECTING"}
            onClick={() => void actions.connect()}
            className={primaryButtonClass}
          >
            Rattacher
          </button>
        )}
        {account.status === "CONNECTED" && !active && (
          <button type="button" disabled={busy} onClick={() => void actions.makeActive()} className={secondaryButtonClass}>
            Rendre actif
          </button>
        )}
        <button
          type="button"
          disabled={busy}
          onClick={() => void actions.setTrading(!account.tradingEnabled)}
          className={secondaryButtonClass}
          title="« Enable / Disable Trading » : un compte désactivé n'accepte aucune entrée, quel que soit le mode"
        >
          {account.tradingEnabled ? "Désactiver le trading" : "Activer le trading"}
        </button>
        {actions.state.status === "busy" && <span className="text-sm text-muted-foreground">{actions.state.what}</span>}
      </div>

      {actions.state.status === "failed" && (
        <div className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm leading-snug" role="alert">
          <p className="text-destructive">{actions.state.failure.message}</p>
          {actions.state.failure.reasons.length > 0 && (
            <ul className="mt-1.5 list-disc pl-4 text-foreground">
              {actions.state.failure.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {account.status !== "CONNECTED" && (
        <p className="mt-4 border-t pt-4 text-sm leading-snug text-muted-foreground">
          Pour le rattacher : ouvre ce compte dans MT5 (Fichier → Connexion à un compte de trading — le mot de passe reste dans
          MT5), puis « Rattacher ». Le cœur vérifie que le terminal est bien sur le login {account.login}.
        </p>
      )}
    </Panel>
  );
}
