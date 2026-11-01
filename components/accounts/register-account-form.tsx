"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import type { AccountRules, AccountType, CreateAccountRequest, Environment, Provider } from "@/lib/api/generated";
import { call } from "@/lib/api/client";
import { ACCOUNT_TYPE_LABELS, formatCapital, PROVIDER_NAMES } from "@/lib/accounts/profile";
import { formatMoney, formatSignedMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { failureOf } from "./use-account-actions";
import { Field, inputClass, primaryButtonClass, secondaryButtonClass } from "./form-controls";

/** The account types each provider offers — the core refuses any other combination, so the form does not offer it. */
const TYPES_BY_PROVIDER: Record<Provider, AccountType[]> = {
  EXNESS: ["DIRECT"],
  FTMO: ["PROP_CHALLENGE", "PROP_VERIFICATION", "PROP_FUNDED"],
};

const PHASE_BY_TYPE: Partial<Record<AccountType, "challenge" | "verification" | "funded">> = {
  PROP_CHALLENGE: "challenge",
  PROP_VERIFICATION: "verification",
  PROP_FUNDED: "funded",
};

const ENVIRONMENTS: Array<{ value: Environment; label: string }> = [
  { value: "DEMO", label: "Démo" },
  { value: "LIVE", label: "Réel" },
  { value: "SIMULATED", label: "Simulé (terminal de démonstration du cœur)" },
];

interface Form {
  name: string;
  provider: Provider;
  accountType: AccountType;
  login: string;
  server: string;
  currency: string;
  environment: Environment;
  terminalPath: string;
  symbolSuffix: string;
  referenceBalance: string;
  challengeType: "1-step" | "2-step";
  accountSize: string;
}

const EMPTY: Form = {
  name: "",
  provider: "EXNESS",
  accountType: "DIRECT",
  login: "",
  server: "",
  currency: "USD",
  environment: "DEMO",
  terminalPath: "",
  symbolSuffix: "",
  referenceBalance: "",
  challengeType: "2-step",
  accountSize: "10000",
};

const number = (text: string): number => Number(text.trim().replace(",", "."));

/** Why the form cannot be sent yet — the core re-checks everything and has the last word. */
function problems(form: Form): string[] {
  const found: string[] = [];
  if (form.name.trim() === "" || form.name.trim().length > 80) {
    found.push("Le nom doit faire de 1 à 80 caractères.");
  }
  const login = number(form.login);
  if (!Number.isInteger(login) || login <= 0) {
    found.push("Le login du compte est un nombre entier positif.");
  }
  if (form.server.trim() === "") {
    found.push("Le serveur est requis (tel que MT5 le nomme).");
  }
  if (!/^[A-Za-z]{3}$/.test(form.currency.trim())) {
    found.push("La devise est un code de trois lettres (USD).");
  }
  if (form.provider === "EXNESS" && form.referenceBalance.trim() !== "") {
    const reference = number(form.referenceBalance);
    if (!Number.isFinite(reference) || reference < 1 || reference > 100_000_000) {
      found.push("Le capital de référence doit être vide ou compris entre 1 et 100 000 000.");
    }
  }
  if (form.provider === "FTMO") {
    const size = number(form.accountSize);
    if (!Number.isFinite(size) || size < 1_000 || size > 10_000_000) {
      found.push("La taille du challenge doit être comprise entre 1 000 et 10 000 000.");
    }
  }
  return found;
}

/** The facts the rules of an account derive from — the core turns them into the complete rule set (and previews it). */
function factsOf(form: Form): Pick<CreateAccountRequest, "referenceBalance" | "challenge"> {
  if (form.provider === "FTMO") {
    return {
      challenge: {
        type: form.challengeType,
        accountSize: number(form.accountSize),
        phase: PHASE_BY_TYPE[form.accountType] ?? "challenge",
      },
    };
  }
  return { referenceBalance: form.referenceBalance.trim() === "" ? null : number(form.referenceBalance) };
}

type State = { status: "idle" } | { status: "saving" } | { status: "saved"; name: string } | { status: "failed"; message: string };

/**
 * Registering an account: which one it is (provider, type, login, server) and how it is to be traded (the facts its rules
 * derive from). **No secret is part of it** — no password is asked, none is stored (ADR 0013): the terminal is logged in by the
 * trader, and the core attaches to it when asked. The rules come from the provider's profile, computed by the core: the preview
 * below is its answer, not a copy of its percentages kept in the page.
 */
export function RegisterAccountForm({ onRegistered }: { onRegistered?: () => void }) {
  const [form, setForm] = useState<Form>(EMPTY);
  const [state, setState] = useState<State>({ status: "idle" });
  const [preview, setPreview] = useState<{ rules: AccountRules | null; error: string | null }>({ rules: null, error: null });

  const issues = useMemo(() => problems(form), [form]);
  const facts = useMemo(() => factsOf(form), [form]);
  const previewKey = issues.length === 0 ? JSON.stringify([form.provider, form.accountType, facts]) : "";

  useEffect(() => {
    if (previewKey === "") {
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      const [provider, accountType, wanted] = JSON.parse(previewKey) as [
        Provider,
        AccountType,
        Pick<CreateAccountRequest, "referenceBalance" | "challenge">,
      ];
      call("accounts_preview_rules", { body: { provider, accountType, ...wanted }, signal: controller.signal }).then(
        (rules) => setPreview({ rules, error: null }),
        (error: unknown) => {
          if (!controller.signal.aborted) {
            setPreview({ rules: null, error: failureOf(error).message });
          }
        },
      );
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [previewKey]);

  function set<K extends keyof Form>(key: K, value: Form[K]) {
    setForm((previous) => ({ ...previous, [key]: value }));
  }

  function setProvider(provider: Provider) {
    setForm((previous) => ({ ...previous, provider, accountType: TYPES_BY_PROVIDER[provider][0] }));
  }

  async function submit() {
    if (issues.length > 0) {
      return;
    }
    const body: CreateAccountRequest = {
      name: form.name.trim(),
      provider: form.provider,
      accountType: form.accountType,
      login: number(form.login),
      server: form.server.trim(),
      currency: form.currency.trim().toUpperCase(),
      environment: form.environment,
      terminalPath: form.terminalPath.trim() === "" ? null : form.terminalPath.trim(),
      symbolSuffix: form.symbolSuffix.trim() === "" ? null : form.symbolSuffix.trim(),
      ...facts,
    };
    setState({ status: "saving" });
    try {
      const created = await call("accounts_create", { body });
      setState({ status: "saved", name: created.name });
      setForm(EMPTY);
      onRegistered?.();
    } catch (error) {
      setState({ status: "failed", message: failureOf(error).message });
    }
  }

  const rules = previewKey === "" ? null : preview.rules;
  const reference = rules?.riskProfile.drawdown.referenceBalance ?? null;
  const saving = state.status === "saving";

  return (
    <Panel
      title="Enregistrer sans se connecter"
      description="quel compte c'est et comment il se trade, à la main — pour un compte dont MT5 n'est pas encore ouvert"
      icon={Plus}
    >
      <form
        id="enregistrer"
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Nom" hint="Comme tu veux le voir dans le cockpit.">
            <input type="text" value={form.name} onChange={(e) => set("name", e.target.value)} maxLength={80} className={inputClass} />
          </Field>
          <Field label="Fournisseur">
            <select value={form.provider} onChange={(e) => setProvider(e.target.value as Provider)} className={inputClass}>
              {(Object.keys(PROVIDER_NAMES) as Provider[]).map((provider) => (
                <option key={provider} value={provider}>
                  {PROVIDER_NAMES[provider]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Type de compte">
            <select
              value={form.accountType}
              onChange={(e) => set("accountType", e.target.value as AccountType)}
              className={inputClass}
            >
              {TYPES_BY_PROVIDER[form.provider].map((type) => (
                <option key={type} value={type}>
                  {ACCOUNT_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Environnement">
            <select
              value={form.environment}
              onChange={(e) => set("environment", e.target.value as Environment)}
              className={inputClass}
            >
              {ENVIRONMENTS.map((environment) => (
                <option key={environment.value} value={environment.value}>
                  {environment.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Login MT5" hint="Le numéro du compte, tel que MT5 l'affiche. Ce n'est pas un mot de passe.">
            <input
              type="text"
              inputMode="numeric"
              value={form.login}
              onChange={(e) => set("login", e.target.value)}
              className={`${inputClass} tnum`}
            />
          </Field>
          <Field label="Serveur" hint="Le nom du serveur dans MT5 (Fichier → Connexion à un compte de trading).">
            <input type="text" value={form.server} onChange={(e) => set("server", e.target.value)} className={inputClass} />
          </Field>
          <Field label="Devise">
            <input
              type="text"
              value={form.currency}
              onChange={(e) => set("currency", e.target.value)}
              maxLength={3}
              className={`${inputClass} uppercase`}
            />
          </Field>
          {form.provider === "FTMO" ? (
            <>
              <Field label="Challenge">
                <select
                  value={form.challengeType}
                  onChange={(e) => set("challengeType", e.target.value as "1-step" | "2-step")}
                  className={inputClass}
                >
                  <option value="2-step">2-Step</option>
                  <option value="1-step">1-Step</option>
                </select>
              </Field>
              <Field label="Taille du challenge ($)" hint="Toutes les limites FTMO sont des pourcentages de cette taille, fixe pour toute sa durée.">
                <input
                  type="text"
                  inputMode="decimal"
                  value={form.accountSize}
                  onChange={(e) => set("accountSize", e.target.value)}
                  className={`${inputClass} tnum`}
                />
              </Field>
            </>
          ) : (
            <Field label="Capital de référence ($)" hint="Le capital engagé. Vide : le solde à la connexion fait foi (à éviter).">
              <input
                type="text"
                inputMode="decimal"
                placeholder="non fixé"
                value={form.referenceBalance}
                onChange={(e) => set("referenceBalance", e.target.value)}
                className={`${inputClass} tnum`}
              />
            </Field>
          )}
          <Field
            label="Chemin du terminal (facultatif)"
            hint="Seulement si plusieurs MT5 sont installés : le terminal.exe de celui de ce compte."
          >
            <input
              type="text"
              value={form.terminalPath}
              onChange={(e) => set("terminalPath", e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field
            label="Suffixe des symboles (facultatif)"
            hint="Comment ce courtier nomme les instruments (« m » chez Exness Standard : EURUSDm). Vide : celui du fournisseur."
          >
            <input
              type="text"
              value={form.symbolSuffix}
              onChange={(e) => set("symbolSuffix", e.target.value)}
              maxLength={10}
              className={inputClass}
            />
          </Field>
        </div>

        {rules && (
          <div className="rounded-lg border bg-muted/40 px-3.5 py-3 text-sm leading-snug">
            <p className="text-foreground">
              Perte journalière max{" "}
              <span className="tnum">
                {reference === null
                  ? `${rules.riskProfile.drawdown.dailyLossLimitPercent} % du solde`
                  : formatSignedMoney(-(reference * rules.riskProfile.drawdown.dailyLossLimitPercent) / 100)}
              </span>{" "}
              · plancher{" "}
              <span className="tnum">
                {reference === null
                  ? `${rules.riskProfile.drawdown.maxDrawdownLimitPercent} % sous le solde`
                  : formatMoney(reference - (reference * rules.riskProfile.drawdown.maxDrawdownLimitPercent) / 100)}
              </span>
              {rules.tradingRules.profitTargetPercent !== null && reference !== null && (
                <>
                  {" "}
                  · objectif{" "}
                  <span className="tnum">{formatCapital((reference * rules.tradingRules.profitTargetPercent) / 100)}</span> (
                  {rules.tradingRules.profitTargetPercent} %) · {rules.tradingRules.minTradingDays} jours minimum
                </>
              )}
            </p>
            {rules.tradingRules.challenge !== null && rules.tradingRules.profitTargetPercent === null && (
              <p className="mt-1.5 text-warning">
                Règles de cette combinaison non sourcées (TODO FTMO-rules) : les objectifs s&apos;afficheront « non sourcé ».
              </p>
            )}
            <p className="mt-1.5 text-muted-foreground">
              Ce sont les limites du profil du fournisseur, calculées par le cœur ; tu les ajustes ensuite dans la section
              Limites, sous la règle anti-tilt.
            </p>
          </div>
        )}
        {previewKey !== "" && preview.error && <p className="text-sm text-destructive">{preview.error}</p>}

        {issues.length > 0 && form !== EMPTY && (
          <ul className="list-disc pl-4 text-sm text-muted-foreground">
            {issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t pt-5">
          <button type="submit" disabled={saving || issues.length > 0} className={primaryButtonClass}>
            {saving ? "Enregistrement…" : "Enregistrer le compte"}
          </button>
          <button type="button" onClick={() => setForm(EMPTY)} disabled={saving} className={secondaryButtonClass}>
            Vider
          </button>
        </div>
        {state.status === "saved" && (
          <p className="text-sm text-success">
            « {state.name} » est enregistré. Ouvre-le dans MT5, puis rattache-le depuis Account.
          </p>
        )}
        {state.status === "failed" && <p className="text-sm text-destructive">{state.message}</p>}
      </form>
    </Panel>
  );
}
