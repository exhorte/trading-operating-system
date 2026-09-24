"use client";

import { useState } from "react";
import { ftmoObjectives, ftmoRiskPolicy, type FtmoChallengeType, type FtmoPhase } from "@/lib/accounts/ftmo";
import {
  ACCOUNT_SIZE_BOUNDS,
  brokerMatchOverlap,
  describeFtmoSettings,
  sameFtmoSettings,
  validateFtmoSettings,
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

/** What saving would make the rule, before it is saved. */
function FtmoPreview({ settings }: { settings: FtmoSettings }) {
  const { challenge } = settings;
  const policy = ftmoRiskPolicy("preview", challenge.phase);
  const objectives = ftmoObjectives(challenge);
  const size = challenge.accountSize;
  if (!Number.isFinite(size) || size <= 0) {
    return null;
  }
  const sourced = objectives.profitTargetPercent !== null;
  return (
    <div className="rounded border border-border bg-muted px-2.5 py-2 text-xs leading-snug">
      <p className="text-foreground">
        Perte journalière max{" "}
        <span className="tnum">{formatSignedMoney(-(size * policy.dailyLossLimitPercent) / 100)}</span> · plancher{" "}
        <span className="tnum">{formatMoney(size - (size * policy.maxDrawdownLimitPercent) / 100)}</span>
        {sourced && (
          <>
            {" "}
            · objectif{" "}
            <span className="tnum">
              {formatSignedMoney((size * objectives.profitTargetPercent!) / 100)}
            </span>{" "}
            · {objectives.minTradingDays} jours minimum
          </>
        )}
      </p>
      {!sourced && (
        <p className="mt-1 text-warning">
          Règles de cette combinaison non sourcées (TODO FTMO-rules) : les limites du 2-Step
          Challenge s&apos;appliquent faute de source, et les objectifs s&apos;affichent « non sourcé ».
        </p>
      )}
    </div>
  );
}

/**
 * Which FTMO challenge is traded: type, size, phase — and the text that
 * recognises FTMO's terminal. Facts about the purchased challenge, not rules:
 * FTMO's percentages stay in `lib/accounts/ftmo.ts`.
 *
 * The draft starts from the target — the pending change if there is one,
 * otherwise what is in effect — so saving again never silently drops a
 * change still waiting for tomorrow.
 */
export function FtmoSettingsForm({
  resolution,
  exness,
  available,
  submitState,
  onSubmit,
}: {
  resolution: FirmResolution<FtmoSettings>;
  /** The other firm's settings in effect — to flag overlapping recognition texts. */
  exness: ExnessSettings;
  available: boolean;
  submitState: SubmitState;
  onSubmit: (settings: FtmoSettings) => void;
}) {
  const target = resolution.pending?.settings ?? resolution.settings;
  const [type, setType] = useState<FtmoChallengeType>(target.challenge.type);
  const [phase, setPhase] = useState<FtmoPhase>(target.challenge.phase);
  const [sizeText, setSizeText] = useState(String(target.challenge.accountSize));
  const [brokerMatch, setBrokerMatch] = useState(target.brokerMatch);

  const draft: FtmoSettings = {
    challenge: { type, phase, accountSize: sizeText.trim() === "" ? Number.NaN : Number(sizeText) },
    brokerMatch: brokerMatch.trim(),
  };
  const errors = validateFtmoSettings(draft);
  const overlap = brokerMatchOverlap({ ftmo: draft, exness });
  const unchanged = sameFtmoSettings(draft, target);
  const saving = submitState.status === "saving";

  function reset() {
    setType(target.challenge.type);
    setPhase(target.challenge.phase);
    setSizeText(String(target.challenge.accountSize));
    setBrokerMatch(target.brokerMatch);
  }

  return (
    <Panel
      title="Prop firm · FTMO"
      actions={
        resolution.source ? (
          <StatusPill tone="info">Configuré</StatusPill>
        ) : (
          <StatusPill tone="muted">Défaut du code</StatusPill>
        )
      }
    >
      <p className="text-xs text-muted-foreground">
        En vigueur : <span className="text-foreground">{describeFtmoSettings(resolution.settings)}</span>
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
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Type de challenge">
            <select
              value={type}
              onChange={(e) => setType(e.target.value as FtmoChallengeType)}
              disabled={!available}
              className={inputClass}
            >
              <option value="2-step">2-Step</option>
              <option value="1-step">1-Step</option>
            </select>
          </Field>
          <Field label="Taille du compte ($)">
            <input
              type="number"
              inputMode="numeric"
              min={ACCOUNT_SIZE_BOUNDS.min}
              max={ACCOUNT_SIZE_BOUNDS.max}
              step={1000}
              value={sizeText}
              onChange={(e) => setSizeText(e.target.value)}
              disabled={!available}
              className={`${inputClass} tnum`}
            />
          </Field>
          <Field label="Phase">
            <select
              value={phase}
              onChange={(e) => setPhase(e.target.value as FtmoPhase)}
              disabled={!available}
              className={inputClass}
            >
              <option value="challenge">Challenge</option>
              <option value="verification">Vérification</option>
              <option value="funded">Funded</option>
            </select>
          </Field>
        </div>
        <Field
          label="Reconnaissance du terminal"
          hint="Texte cherché, sans tenir compte de la casse, dans le nom de broker que MT5 transmet. Aucun terminal FTMO n'a encore été branché : si le nom réel ne contient pas « ftmo », corrige-le ici."
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

        <FtmoPreview settings={draft} />

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
