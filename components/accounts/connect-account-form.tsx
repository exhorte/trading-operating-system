"use client";

import { useRef, useState } from "react";
import { PlugZap } from "lucide-react";
import { cn } from "cn";
import type { DiscoveredAccount, Environment, Provider } from "@/lib/api/generated";
import { call } from "@/lib/api/client";
import { useCockpit } from "@/lib/realtime/provider";
import { connectedAccount } from "@/lib/accounts/connected";
import {
  blockers,
  loginOf,
  registrationFor,
  reviewOf,
  type Review,
  type RulesProfile,
  type Wanted,
} from "@/lib/accounts/connect";
import { PROVIDER_NAMES } from "@/lib/accounts/profile";
import { formatDateTime, formatMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { failureOf, useAccountActions } from "./use-account-actions";
import { Field, inputClass, primaryButtonClass, secondaryButtonClass } from "./form-controls";

/** The two accounts the trader can add. Not a free choice of broker: each brings its own rules (ADR 0020). */
const PROVIDER_CHOICES: Array<{ provider: Provider; text: string }> = [
  { provider: "EXNESS", text: "Compte direct, démo ou réel" },
  { provider: "FTMO", text: "Challenge 2-Step : sa taille est le capital initial que tu confirmes" },
];

const ENVIRONMENTS: Array<{ value: Environment; label: string }> = [
  { value: "DEMO", label: "Démo" },
  { value: "LIVE", label: "Réel" },
];

type Phase =
  | { step: "identify" }
  | { step: "reading" }
  | { step: "review"; found: DiscoveredAccount; review: Review }
  | { step: "saving"; found: DiscoveredAccount; review: Review }
  | { step: "done"; name: string; attached: boolean; note: string | null };

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="tnum text-sm text-foreground">{value}</dd>
    </div>
  );
}

const yesNo = (value: boolean) => (value ? "oui" : "non");

/** Everything the broker said about the account — read, not typed. */
function Facts({ found }: { found: DiscoveredAccount }) {
  const money = (value: number) => formatMoney(value, found.currency);
  return (
    <div className="flex flex-col gap-4 rounded-lg border bg-muted/40 px-3.5 py-3.5">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <Fact label="Courtier" value={found.company || "—"} />
        <Fact label="Serveur" value={found.server} />
        <Fact label="Login" value={String(found.login)} />
        <Fact label="Type" value={found.tradeMode === "demo" ? "démo" : found.tradeMode === "real" ? "réel" : found.tradeMode} />
        <Fact label="Solde" value={money(found.balance)} />
        <Fact label="Équité" value={money(found.equity)} />
        <Fact label="Levier" value={found.leverage > 0 ? `1:${found.leverage}` : "—"} />
        <Fact label="Devise" value={found.currency} />
        <Fact label="Marge utilisée" value={money(found.margin)} />
        <Fact label="Marge libre" value={money(found.marginFree)} />
        <Fact label="Niveau de marge" value={found.marginLevel === null ? "— (aucune marge)" : `${found.marginLevel.toFixed(0)} %`} />
        <Fact label="Mode de marge" value={found.marginMode === "hedging" ? "hedging" : found.marginMode} />
        <Fact label="Clôture FIFO" value={yesNo(found.fifoClose)} />
        <Fact label="Trading autorisé" value={yesNo(found.tradeAllowed)} />
        <Fact label="Trading automatique" value={yesNo(found.tradeExpert)} />
        <Fact label="Positions · ordres" value={`${found.openPositions} · ${found.pendingOrders}`} />
      </dl>
      {found.symbols.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs text-muted-foreground">
            Instruments tels que ce courtier les nomme{found.symbolSuffix ? ` (suffixe « ${found.symbolSuffix} »)` : ""}
          </p>
          <ul className="flex flex-col gap-1 text-sm">
            {found.symbols.map((symbol) => (
              <li key={symbol.brokerName} className="tnum flex flex-wrap gap-x-4 text-foreground">
                <span className="font-medium">{symbol.brokerName}</span>
                <span className="text-muted-foreground">
                  lot min {symbol.volumeMin} · pas {symbol.volumeStep} · contrat {symbol.contractSize} · tick {symbol.tickSize}{" "}
                  = {symbol.tickValue} {found.currency}
                  {symbol.spread !== null && ` · spread ${symbol.spread}`}
                  {!symbol.tradable && " · non négociable"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {found.warnings.length > 0 && (
        <ul className="list-disc pl-4 text-sm text-warning">
          {found.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Connecting an account from its broker identifiers (ADR 0013, 0020): the trader gives the login, the server and — if MT5 is not
 * already logged into that account — the password; the core reads everything the broker says about the account; the trader checks
 * it, confirms the initial capital, and the account is registered and attached.
 *
 * **The password** goes from this field to the core and nowhere else (ADR 0013): the field has no `name`, is not controlled by
 * React, is read by ref at the moment of sending and emptied in a `finally`; the request carries no cache, no cookie, no
 * referrer. The core uses it once and keeps nothing. Registering and attaching afterwards need none: the terminal is logged in.
 */
export function ConnectAccountForm({ onRegistered }: { onRegistered?: () => void }) {
  const { accounts } = useCockpit();
  const connected = connectedAccount(accounts);
  const detach = useAccountActions(connected?.id ?? "");
  const passwordRef = useRef<HTMLInputElement>(null);
  const [wanted, setWanted] = useState<Wanted>({ provider: "EXNESS", rules: "own" });
  const [login, setLogin] = useState("");
  const [server, setServer] = useState("");
  const [terminalPath, setTerminalPath] = useState("");
  const [phase, setPhase] = useState<Phase>({ step: "identify" });
  const [error, setError] = useState<string | null>(null);

  const loginNumber = loginOf(login);
  const canRead = loginNumber !== null && server.trim() !== "" && phase.step !== "reading";

  function setProvider(provider: Provider) {
    setWanted({ provider, rules: "own" });
  }

  async function read() {
    if (loginNumber === null) {
      return;
    }
    setError(null);
    setPhase({ step: "reading" });
    try {
      const typed = passwordRef.current?.value ?? "";
      const found = await call("accounts_discover", {
        body: {
          login: loginNumber,
          server: server.trim(),
          password: typed === "" ? null : typed,
          terminalPath: terminalPath.trim() === "" ? null : terminalPath.trim(),
        },
      });
      setPhase({ step: "review", found, review: reviewOf(found) });
    } catch (failure) {
      setError(failureOf(failure).message);
      setPhase({ step: "identify" });
    } finally {
      if (passwordRef.current) {
        passwordRef.current.value = "";
      }
    }
  }

  async function save(found: DiscoveredAccount, review: Review) {
    if (blockers(found, wanted, review).length > 0) {
      return;
    }
    setError(null);
    setPhase({ step: "saving", found, review });
    try {
      const created = await call("accounts_create", { body: registrationFor(found, wanted, review) });
      onRegistered?.();
      try {
        await call("accounts_connect", { path: { account_id: created.id } });
        setPhase({ step: "done", name: created.name, attached: true, note: null });
      } catch (failure) {
        setPhase({ step: "done", name: created.name, attached: false, note: failureOf(failure).message });
      }
    } catch (failure) {
      setError(failureOf(failure).message);
      setPhase({ step: "review", found, review });
    }
  }

  function restart() {
    setError(null);
    setPhase({ step: "identify" });
  }

  const reviewing = phase.step === "review" || phase.step === "saving";
  const issues = reviewing ? blockers(phase.found, wanted, phase.review) : [];

  // One account at a time (ADR 0021): while another is connected there is nothing to fill in — it has to be detached first.
  if (connected !== null && phase.step === "identify") {
    return (
      <Panel
        title="Un compte est connecté"
        description="un seul compte à la fois : détache-le pour en connecter un autre"
        icon={PlugZap}
      >
        <div className="flex flex-col gap-3">
          <p className="text-sm text-foreground">
            {PROVIDER_NAMES[connected.provider]} · {connected.name} · <span className="tnum">{connected.login}</span> ·{" "}
            {connected.server}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={detach.state.status === "busy"}
              onClick={() => void detach.disconnect()}
              className={secondaryButtonClass}
            >
              {detach.state.status === "busy" ? detach.state.what : `Détacher « ${connected.name} »`}
            </button>
          </div>
          {detach.state.status === "failed" && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm leading-snug" role="alert">
              <p className="text-destructive">{detach.state.failure.message}</p>
              {detach.state.failure.reasons.length > 0 && (
                <ul className="mt-1.5 list-disc pl-4 text-foreground">
                  {detach.state.failure.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </Panel>
    );
  }

  return (
    <Panel
      title="Connecter un compte"
      description="les identifiants du courtier → le cœur lit le compte chez lui → tu vérifies → il est enregistré et rattaché"
      icon={PlugZap}
    >
      {phase.step === "done" ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-success">
            « {phase.name} » est enregistré{phase.attached ? " et rattaché au terminal." : "."}
          </p>
          {phase.note && (
            <p className="text-sm text-warning">
              Pas encore rattaché : {phase.note} Ouvre le compte dans MT5, puis rattache-le depuis Account.
            </p>
          )}
          <div>
            <button type="button" onClick={restart} className={secondaryButtonClass}>
              Connecter un autre compte
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <form
            className="grid grid-cols-1 gap-4 sm:grid-cols-2"
            autoComplete="off"
            onSubmit={(event) => {
              event.preventDefault();
              if (canRead && !reviewing) {
                void read();
              }
            }}
          >
            <div className="sm:col-span-2" role="radiogroup" aria-label="Quel compte veux-tu ajouter ?">
              <p className="mb-2 text-[0.8125rem] text-muted-foreground">Quel compte veux-tu ajouter ?</p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {PROVIDER_CHOICES.map((choice) => {
                  const selected = wanted.provider === choice.provider;
                  return (
                    <button
                      key={choice.provider}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={reviewing || phase.step === "reading"}
                      onClick={() => setProvider(choice.provider)}
                      className={cn(
                        "flex flex-col gap-0.5 rounded-lg border px-4 py-3 text-left transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-60",
                        selected ? "border-foreground bg-accent" : "hover:bg-accent/60",
                      )}
                    >
                      <span className="text-sm font-semibold text-foreground">{PROVIDER_NAMES[choice.provider]}</span>
                      <span className="text-xs leading-snug text-muted-foreground">{choice.text}</span>
                    </button>
                  );
                })}
              </div>
            </div>
            {wanted.provider === "EXNESS" && (
              <Field
                label="Règles à suivre"
                hint="Les règles internes sont les mêmes ; le profil FTMO ajoute le contrat du challenge (−5 % / −10 %), sa taille et ses objectifs. Démo seulement."
              >
                <select
                  value={wanted.rules}
                  onChange={(e) => setWanted({ ...wanted, rules: e.target.value as RulesProfile })}
                  disabled={reviewing || phase.step === "reading"}
                  className={inputClass}
                >
                  <option value="own">Celles d&apos;Exness (compte direct)</option>
                  <option value="ftmo">Profil FTMO Challenge 2-Step — répété sur cette démo</option>
                </select>
              </Field>
            )}
            <Field label="Login MT5" hint="Le numéro du compte, tel que MT5 l'affiche.">
              <input
                type="text"
                inputMode="numeric"
                autoComplete="off"
                value={login}
                onChange={(e) => setLogin(e.target.value)}
                disabled={reviewing || phase.step === "reading"}
                className={`${inputClass} tnum`}
              />
            </Field>
            <Field label="Serveur" hint="Tel que MT5 le nomme, par exemple Exness-MT5Trial10 ou FTMO-Server3.">
              <input
                type="text"
                autoComplete="off"
                value={server}
                onChange={(e) => setServer(e.target.value)}
                disabled={reviewing || phase.step === "reading"}
                className={inputClass}
              />
            </Field>
            {/* No `name`, no `value`: React never holds it (ADR 0013). Read by ref when sending, emptied in a `finally`. */}
            <Field
              label="Mot de passe (facultatif)"
              hint="Laisse vide si MT5 est déjà connecté à ce compte. Le mot de passe investisseur suffit pour lire. Il n'est ni gardé, ni journalisé, ni renvoyé."
            >
              <input
                ref={passwordRef}
                type="password"
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                maxLength={256}
                disabled={reviewing || phase.step === "reading"}
                className={inputClass}
              />
            </Field>
            <Field label="Chemin du terminal (facultatif)" hint="Seulement si plusieurs MT5 sont installés : le terminal64.exe de celui de ce compte.">
              <input
                type="text"
                autoComplete="off"
                value={terminalPath}
                onChange={(e) => setTerminalPath(e.target.value)}
                disabled={reviewing || phase.step === "reading"}
                className={inputClass}
              />
            </Field>
            {!reviewing && (
              <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
                <button type="submit" disabled={!canRead} className={primaryButtonClass}>
                  {phase.step === "reading" ? "Lecture chez le courtier…" : "Lire le compte chez le courtier"}
                </button>
              </div>
            )}
          </form>

          {reviewing && (
            <>
              <Facts found={phase.found} />
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Nom dans le cockpit">
                  <input
                    type="text"
                    value={phase.review.name}
                    maxLength={80}
                    onChange={(e) => setPhase({ ...phase, review: { ...phase.review, name: e.target.value } })}
                    disabled={phase.step === "saving"}
                    className={inputClass}
                  />
                </Field>
                <Field label="Environnement">
                  <select
                    value={phase.review.environment}
                    onChange={(e) =>
                      setPhase({ ...phase, review: { ...phase.review, environment: e.target.value as Environment } })
                    }
                    disabled={phase.step === "saving"}
                    className={inputClass}
                  >
                    {ENVIRONMENTS.map((environment) => (
                      <option key={environment.value} value={environment.value}>
                        {environment.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field
                  label={`Capital initial (${phase.found.currency})`}
                  hint={
                    phase.found.capital.reliable
                      ? `Premier dépôt lu dans l'historique du courtier${phase.found.capital.at ? ` (${formatDateTime(phase.found.capital.at)})` : ""}.`
                      : "Le courtier n'indique pas le capital de départ : c'est le solde actuel qui est proposé. Corrige-le si le compte a déjà bougé."
                  }
                >
                  <input
                    type="text"
                    inputMode="decimal"
                    value={phase.review.capital}
                    onChange={(e) =>
                      setPhase({ ...phase, review: { ...phase.review, capital: e.target.value, capitalConfirmed: false } })
                    }
                    disabled={phase.step === "saving"}
                    className={`${inputClass} tnum`}
                  />
                </Field>
                <label className="flex items-start gap-2 self-end pb-1 text-sm text-foreground">
                  <input
                    type="checkbox"
                    checked={phase.review.capitalConfirmed}
                    onChange={(e) =>
                      setPhase({ ...phase, review: { ...phase.review, capitalConfirmed: e.target.checked } })
                    }
                    disabled={phase.step === "saving"}
                    className="mt-0.5"
                  />
                  <span>Ce montant est le capital initial de ce compte.</span>
                </label>
              </div>
              {issues.length > 0 && (
                <ul className="list-disc pl-4 text-sm text-muted-foreground">
                  {issues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              )}
              <div className="flex flex-wrap items-center gap-2 border-t pt-5">
                <button
                  type="button"
                  disabled={phase.step === "saving" || issues.length > 0}
                  onClick={() => void save(phase.found, phase.review)}
                  className={primaryButtonClass}
                >
                  {phase.step === "saving" ? "Enregistrement…" : "Enregistrer et rattacher"}
                </button>
                <button type="button" onClick={restart} disabled={phase.step === "saving"} className={secondaryButtonClass}>
                  Recommencer
                </button>
              </div>
            </>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
      )}
    </Panel>
  );
}
