"use client";

import { useMemo, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import type { Account, RulesOverview } from "@/lib/api/generated";
import { call } from "@/lib/api/client";
import { describeApplication } from "@/lib/accounts/guard-text";
import {
  applyDraft,
  describeChange,
  draftOf,
  editableFields,
  FIELDS_BY_ID,
  isUnchanged,
  SECTIONS,
  withConfigured,
  type Draft,
  type FieldId,
  type SectionId,
} from "@/lib/accounts/rules-draft";
import { formatMoney, formatSignedMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import { failureOf } from "./use-account-actions";
import { Field, inputClass, primaryButtonClass, secondaryButtonClass } from "./form-controls";
import { PendingChange } from "./pending-change";

const SECTION_ORDER: SectionId[] = ["capital", "risk", "discipline", "market", "execution"];

type SubmitState = { status: "idle" } | { status: "saving" } | { status: "failed"; message: string };

/**
 * What the core answered to a save. It lives in the *page*, not in the form: the form is keyed by the version it starts from, so
 * the save itself — which adds a version — replaces the form, and a message held by it would be gone before it could be read.
 */
export interface SavedNotice {
  accountId: string;
  message: string;
  /** The change waits for the next trading day (the anti-tilt guard) rather than applying now. */
  deferred: boolean;
}

/** What saving would make of the loss limits in money, before it is saved. */
function Preview({
  reference,
  daily,
  weekly,
  drawdown,
}: {
  reference: number | null;
  daily: number;
  weekly: number;
  drawdown: number;
}) {
  if (reference === null) {
    return (
      <div className="rounded-lg border bg-muted/40 px-3.5 py-3 text-sm leading-snug">
        <p>
          Aucune référence fixe : les limites ({daily} % par jour, {weekly} % par semaine, {drawdown} % au total) se calculent
          en pourcentage du solde au moment où le compte s&apos;est rattaché — ce solde change à chaque reconnexion, donc les
          montants et le plancher aussi.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-lg border bg-muted/40 px-3.5 py-3 text-sm leading-snug">
      <p>
        Perte journalière max <span className="tnum">{formatSignedMoney(-(reference * daily) / 100)}</span> · hebdomadaire max{" "}
        <span className="tnum">{formatSignedMoney(-(reference * weekly) / 100)}</span> · plancher{" "}
        <span className="tnum">{formatMoney(reference - (reference * drawdown) / 100)}</span>, fixes quelle que soit l&apos;heure
        de connexion.
      </p>
    </div>
  );
}

/**
 * The limits of one account — the numbers the Risk Engine enforces and the strategy is held to (ADR 0015: *every value is set by
 * the user, account by account, none is « unlimited »*).
 *
 * Saving appends a version to the account's ledger. The core decides *at that instant* whether it applies at once or at the
 * next trading day (the anti-tilt guard: a limit never loosens mid-session — ADR 0007) and says so in the answer, which this
 * form reports as it came. What this form cannot reach — the autonomy ceiling, the trading windows, the challenge — is carried
 * over untouched.
 *
 * The draft starts from the target — the change waiting for tomorrow if there is one, otherwise what is in effect — so saving
 * again never silently drops a change still waiting.
 */
export function RulesForm({
  account,
  overview,
  onChanged,
  notice,
  onNotice,
}: {
  account: Account;
  overview: RulesOverview;
  onChanged: () => void;
  /** The core's answer to the last save, kept by the page across the form's replacement; null once it is stale. */
  notice: SavedNotice | null;
  onNotice: (notice: SavedNotice | null) => void;
}) {
  const { resolution } = overview;
  const target = resolution.pending?.rules ?? resolution.rules;
  const [draft, setDraft] = useState<Draft>(() => draftOf(target));
  const [confirmed, setConfirmed] = useState(target.riskProfile.configured);
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  const fields = useMemo(() => editableFields(target), [target]);
  const applied = useMemo(() => applyDraft(target, draft), [target, draft]);
  const unchanged = isUnchanged(target, draft) && confirmed === target.riskProfile.configured;
  const saving = state.status === "saving";
  const valid = applied.rules !== null;
  const drawdown = applied.rules?.riskProfile.drawdown ?? target.riskProfile.drawdown;

  function set(id: FieldId, value: string) {
    setDraft((previous) => ({ ...previous, [id]: value }));
    onNotice(null); // a new edit: the answer to the previous save is no longer about what is on screen
  }

  function reset() {
    setDraft(draftOf(target));
    setConfirmed(target.riskProfile.configured);
    onNotice(null);
  }

  async function save() {
    if (applied.rules === null || unchanged) {
      return;
    }
    const rules = withConfigured(applied.rules, confirmed);
    setState({ status: "saving" });
    onNotice(null);
    try {
      const version = await call("accounts_request_rules", { path: { account_id: account.id }, body: rules });
      setState({ status: "idle" });
      onNotice({
        accountId: account.id,
        deferred: version.deferred,
        message: `Enregistré — ${describeApplication(version)}`,
      });
    } catch (error) {
      setState({ status: "failed", message: failureOf(error).message });
    } finally {
      onChanged();
    }
  }

  const changes = applied.rules ? describeChange(target, withConfigured(applied.rules, confirmed)) : [];

  return (
    <Panel
      title={`Limites · ${account.name}`}
      description="les nombres que le moteur de risque fait respecter"
      icon={SlidersHorizontal}
      actions={
        target.riskProfile.configured ? (
          <StatusPill tone="info">Écrites par toi</StatusPill>
        ) : (
          <StatusPill tone="warning">Valeurs par défaut</StatusPill>
        )
      }
    >
      {resolution.pending && (
        <div className="mb-4">
          <PendingChange
            version={overview.versions.find((v) => v.versionId === resolution.pending?.versionId) ?? { ...resolution.pending, status: "pending", cancellable: false }}
            inForce={resolution.rules}
            onChanged={() => {
              onNotice(null); // the change it announced is gone (cancelled, or taken into force)
              onChanged();
            }}
          />
        </div>
      )}

      <form
        className="flex flex-col gap-6"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        {SECTION_ORDER.map((section) => {
          const inSection = fields.filter((field) => field.section === section);
          if (inSection.length === 0) {
            return null;
          }
          return (
            <fieldset key={section} className="flex flex-col gap-4">
              <legend className="mb-1 text-sm font-semibold text-foreground">
                {SECTIONS[section].title}
                <span className="ml-2 font-normal text-muted-foreground">{SECTIONS[section].description}</span>
              </legend>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {inSection.map((field) => (
                  <Field
                    key={field.id}
                    label={field.unit ? `${field.label} (${field.unit})` : field.label}
                    hint={field.hint}
                  >
                    <input
                      type="text"
                      inputMode={field.integer ? "numeric" : "decimal"}
                      placeholder={field.nullable ? "non fixé" : undefined}
                      value={draft[field.id]}
                      onChange={(e) => set(field.id, e.target.value)}
                      className={`${inputClass} tnum`}
                      aria-label={FIELDS_BY_ID[field.id].label}
                    />
                  </Field>
                ))}
              </div>
            </fieldset>
          );
        })}

        {account.tradingRules.challenge === null ? null : (
          <p className="text-sm leading-snug text-muted-foreground">
            Le capital de référence d&apos;un challenge est sa taille ({formatMoney(account.tradingRules.challenge.accountSize)}),
            fixe pour toute sa durée : il ne se règle pas ici. Un nouveau challenge est un nouveau compte.
          </p>
        )}

        <Preview
          reference={drawdown.referenceBalance}
          daily={drawdown.dailyLossLimitPercent}
          weekly={drawdown.weeklyLossLimitPercent}
          drawdown={drawdown.maxDrawdownLimitPercent}
        />

        <label className="flex items-start gap-2.5 text-sm leading-snug">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            className="mt-0.5 size-4 accent-primary"
          />
          <span>
            <span className="text-foreground">Ces limites sont les miennes.</span>{" "}
            <span className="text-muted-foreground">
              Tant que tu ne l&apos;as pas coché, le cœur les tient pour des valeurs par défaut, et l&apos;autonomie refuse de
              démarrer (contrôle « limites du compte configurées »).
            </span>
          </span>
        </label>

        {applied.errors.length > 0 && (
          <ul className="list-disc pl-4 text-sm text-destructive">
            {applied.errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}

        {valid && changes.length > 0 && (
          <div className="rounded-lg border bg-muted/40 px-3.5 py-3 text-sm leading-snug">
            <p className="font-medium text-foreground">Ce que l&apos;enregistrement changerait</p>
            <ul className="mt-1.5 list-disc pl-4 text-muted-foreground">
              {changes.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t pt-5">
          <button type="submit" disabled={saving || unchanged || !valid} className={primaryButtonClass}>
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
          <button type="button" onClick={reset} disabled={unchanged || saving} className={secondaryButtonClass}>
            Rétablir
          </button>
          {unchanged && <span className="text-sm text-muted-foreground">Aucune modification.</span>}
        </div>

        {notice !== null && notice.accountId === account.id && (
          <p role="status" className={`text-sm ${notice.deferred ? "text-warning" : "text-success"}`}>
            {notice.message}
          </p>
        )}
        {state.status === "failed" && <p className="text-sm text-destructive">{state.message}</p>}
      </form>
    </Panel>
  );
}
