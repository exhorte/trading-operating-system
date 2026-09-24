"use client";

import { useState } from "react";
import { realRiskPolicy } from "@/lib/accounts/real";
import {
  brokerMatchOverlap,
  describeExnessSettings,
  REFERENCE_BALANCE_BOUNDS,
  sameExnessSettings,
  validateExnessSettings,
  type ExnessSettings,
  type FirmResolution,
  type FtmoSettings,
} from "@/lib/accounts/settings";
import { formatMoney, formatSignedMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import { Field, formatDateTime, inputClass, primaryButtonClass, secondaryButtonClass } from "./form-controls";
import { PendingChange } from "./pending-change";
import type { SubmitState } from "./use-settings-submit";

function ExnessPreview({ settings }: { settings: ExnessSettings }) {
  const policy = realRiskPolicy("preview");
  const ref = settings.referenceBalance;
  if (ref !== null && (!Number.isFinite(ref) || ref <= 0)) {
    return null;
  }
  return (
    <div className="rounded border border-border bg-muted px-2.5 py-2 text-xs leading-snug text-foreground">
      {ref === null ? (
        <p>
          Aucune référence fixe : les deux limites (5 % par jour, 10 % au total) se calculent en
          pourcentage du solde au moment où le cockpit s&apos;est connecté — ce solde change à
          chaque reconnexion, donc les montants et le plancher aussi. C&apos;est le comportement
          d&apos;avant T12.
        </p>
      ) : (
        <p>
          Perte journalière max{" "}
          <span className="tnum">{formatSignedMoney(-(ref * policy.dailyLossLimitPercent) / 100)}</span> ·
          plancher{" "}
          <span className="tnum">{formatMoney(ref - (ref * policy.maxDrawdownLimitPercent) / 100)}</span>, fixes
          quelle que soit l&apos;heure de connexion du cockpit.
        </p>
      )}
    </div>
  );
}

/**
 * The direct Exness account: the capital its overall loss is measured from,
 * and the text that recognises Exness's terminal. The 5 %/10 % limits are the
 * trader's own decision of 2026-09-21 and stay in `lib/accounts/real.ts`.
 */
export function ExnessSettingsForm({
  resolution,
  ftmo,
  available,
  submitState,
  onSubmit,
}: {
  resolution: FirmResolution<ExnessSettings>;
  /** The other firm's settings in effect — to flag overlapping recognition texts. */
  ftmo: FtmoSettings;
  available: boolean;
  submitState: SubmitState;
  onSubmit: (settings: ExnessSettings) => void;
}) {
  const target = resolution.pending?.settings ?? resolution.settings;
  const [referenceText, setReferenceText] = useState(
    target.referenceBalance === null ? "" : String(target.referenceBalance),
  );
  const [brokerMatch, setBrokerMatch] = useState(target.brokerMatch);

  const draft: ExnessSettings = {
    referenceBalance: referenceText.trim() === "" ? null : Number(referenceText),
    brokerMatch: brokerMatch.trim(),
  };
  const errors = validateExnessSettings(draft);
  const overlap = brokerMatchOverlap({ ftmo, exness: draft });
  const unchanged = sameExnessSettings(draft, target);
  const saving = submitState.status === "saving";

  function reset() {
    setReferenceText(target.referenceBalance === null ? "" : String(target.referenceBalance));
    setBrokerMatch(target.brokerMatch);
  }

  return (
    <Panel
      title="Broker · Exness"
      actions={
        resolution.source ? (
          <StatusPill tone="info">Configuré</StatusPill>
        ) : (
          <StatusPill tone="muted">Défaut du code</StatusPill>
        )
      }
    >
      <p className="text-xs text-muted-foreground">
        En vigueur : <span className="text-foreground">{describeExnessSettings(resolution.settings)}</span>
        {resolution.source ? ` — depuis le ${formatDateTime(resolution.source.requestedAt)}` : ""}
      </p>
      {resolution.pending && (
        <div className="mt-2">
          <PendingChange version={resolution.pending} />
        </div>
      )}

      <form
        className="mt-3 flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (errors.length === 0 && !unchanged) {
            onSubmit(draft);
          }
        }}
      >
        <Field
          label="Capital de référence ($)"
          hint="Le capital engagé sur ce compte. Les deux limites de perte se calculent en pourcentage de ce montant, et le plancher de la perte max s'en déduit. Laisser vide pour ne pas en fixer."
        >
          <input
            type="number"
            inputMode="decimal"
            min={REFERENCE_BALANCE_BOUNDS.min}
            max={REFERENCE_BALANCE_BOUNDS.max}
            step="any"
            placeholder="non fixé"
            value={referenceText}
            onChange={(e) => setReferenceText(e.target.value)}
            disabled={!available}
            className={`${inputClass} tnum`}
          />
        </Field>
        <Field
          label="Reconnaissance du terminal"
          hint="Texte cherché, sans tenir compte de la casse, dans le nom de broker que MT5 transmet."
        >
          <input
            type="text"
            value={brokerMatch}
            onChange={(e) => setBrokerMatch(e.target.value)}
            disabled={!available}
            className={inputClass}
            maxLength={64}
          />
        </Field>

        <ExnessPreview settings={draft} />

        {overlap && <p className="text-xs text-warning">{overlap}</p>}
        {errors.length > 0 && (
          <ul className="list-disc pl-4 text-xs text-loss">
            {errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={!available || saving || unchanged || errors.length > 0}
            className={primaryButtonClass}
          >
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
          <button type="button" onClick={reset} disabled={unchanged || saving} className={secondaryButtonClass}>
            Rétablir
          </button>
          {unchanged && available && <span className="text-xs text-muted-foreground">Aucune modification.</span>}
        </div>

        {submitState.status === "saved" && (
          <p className={`text-xs ${submitState.version.deferred ? "text-warning" : "text-profit"}`}>
            {submitState.message}
          </p>
        )}
        {submitState.status === "failed" && <p className="text-xs text-loss">{submitState.message}</p>}
      </form>
    </Panel>
  );
}
