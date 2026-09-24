"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { exnessProfile, ftmoProfile, type ActiveProfile } from "@/lib/accounts/active-profile";
import { observerCommand } from "@/lib/accounts/connection";
import type { Firm } from "@/lib/accounts/firm";
import { ftmoObjectives } from "@/lib/accounts/ftmo";
import type { ResolvedAccountSettings } from "@/lib/accounts/settings";
import { formatMoney, formatSignedMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import { formatDateTime } from "./form-controls";
import { PendingChange } from "./pending-change";

export const FIRM_TITLES: Record<Firm, string> = {
  ftmo: "Prop firm · FTMO",
  exness: "Broker · Exness",
};

function Row({ label, children, tone = "text-foreground" }: { label: string; children: ReactNode; tone?: string }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={`tnum text-right ${tone}`}>{children}</dd>
    </>
  );
}

function limitsOf(profile: ActiveProfile) {
  const ref = profile.referenceBalance;
  const p = profile.riskPolicy;
  return {
    daily: ref === null ? null : (ref * p.dailyLossLimitPercent) / 100,
    floor: ref === null ? null : ref - (ref * p.maxDrawdownLimitPercent) / 100,
  };
}

/**
 * One configured account — FTMO or Exness — whether or not it is the one MT5
 * has open. The rules shown are the settings in effect today (the same
 * resolution as the risk engine); live figures appear only for the account
 * the observer is attached to (one account at a time, T12 décision 1).
 */
export function FirmAccountCard({
  firm,
  resolved,
  connectedFirm,
}: {
  firm: Firm;
  resolved: ResolvedAccountSettings;
  connectedFirm: Firm | null;
}) {
  const { account, risk } = useCockpit();
  const connected = connectedFirm === firm && account !== null;
  const accountId = connected ? account.accountId : "—";
  const resolution = resolved[firm];
  const profile =
    firm === "ftmo"
      ? ftmoProfile(accountId, resolved.settings.ftmo.challenge)
      : exnessProfile(accountId, resolved.settings.exness.referenceBalance);
  const { daily, floor } = limitsOf(profile);
  const p = profile.riskPolicy;

  return (
    <Panel
      title={FIRM_TITLES[firm]}
      actions={
        connected ? (
          <StatusPill tone="profit" pulse>
            Connecté
          </StatusPill>
        ) : (
          <StatusPill tone="muted">Non connecté</StatusPill>
        )
      }
    >
      <p className="text-sm font-semibold tracking-tight text-foreground">{profile.label}</p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {resolution.source
          ? `Configuré dans Settings le ${formatDateTime(resolution.source.requestedAt)}`
          : "Valeurs par défaut du code — aucun réglage de Settings n'est en vigueur"}
      </p>

      <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-xs">
        {firm === "ftmo" ? (
          <FtmoRows profile={profile} daily={daily} floor={floor} />
        ) : (
          <>
            <Row label="Capital de référence" tone={profile.referenceBalance === null ? "text-warning" : "text-foreground"}>
              {profile.referenceBalance === null ? "non fixé" : formatMoney(profile.referenceBalance)}
            </Row>
            <Row label={`Perte journalière max (${p.dailyLossLimitPercent} %)`}>
              {daily === null ? "sur le solde à la connexion" : formatSignedMoney(-daily)}
            </Row>
            <Row label={`Plancher (perte max ${p.maxDrawdownLimitPercent} %)`}>
              {floor === null ? "aucun plancher fixe" : formatMoney(floor)}
            </Row>
          </>
        )}
        <Row label="Reconnu quand le broker contient">« {resolved.settings[firm].brokerMatch} »</Row>
      </dl>

      {connected && (
        <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 border-t border-border pt-3 text-xs">
          <Row label="Compte">{account.label}</Row>
          <Row label="Solde">{formatMoney(account.balance, account.currency)}</Row>
          <Row label="Equity">{formatMoney(account.equity, account.currency)}</Row>
          {floor !== null && (
            // Same measure as the objectives' max-loss row: the lower of
            // balance and equity, so a floating loss counts.
            <Row
              label="Marge avant le plancher"
              tone={Math.min(account.balance, account.equity) - floor <= 0 ? "text-loss" : "text-foreground"}
            >
              {formatMoney(Math.max(0, Math.min(account.balance, account.equity) - floor), account.currency)}
            </Row>
          )}
          {risk && (
            <Row label="Perte du jour utilisée">
              {risk.dailyLossUsedPercent.toFixed(1)} % sur {risk.dailyLossLimitPercent} %
            </Row>
          )}
        </dl>
      )}

      {resolution.pending && (
        <div className="mt-3">
          <PendingChange version={resolution.pending} allowCancel={false} />
        </div>
      )}

      {!connected && (
        <p className="mt-3 border-t border-border pt-3 text-xs leading-snug text-muted-foreground">
          Pour le brancher : ouvre ce compte dans MT5, puis lance{" "}
          <code className="text-foreground">{observerCommand(firm)}</code>.{" "}
          <Link href="/settings#connexion" className="text-primary hover:underline">
            Procédure complète
          </Link>
        </p>
      )}
    </Panel>
  );
}

function FtmoRows({
  profile,
  daily,
  floor,
}: {
  profile: ActiveProfile;
  daily: number | null;
  floor: number | null;
}) {
  const challenge = profile.challenge!;
  const objectives = ftmoObjectives(challenge);
  const p = profile.riskPolicy;
  return (
    <>
      <Row label="Taille du compte">{formatMoney(challenge.accountSize)}</Row>
      <Row label={`Perte journalière max (${p.dailyLossLimitPercent} %)`}>
        {daily === null ? "—" : formatSignedMoney(-daily)}
      </Row>
      <Row label={`Plancher (perte max ${p.maxDrawdownLimitPercent} %)`}>
        {floor === null ? "—" : formatMoney(floor)}
      </Row>
      <Row
        label="Objectif de profit"
        tone={objectives.profitTargetPercent === null ? "text-muted-foreground" : "text-foreground"}
      >
        {objectives.profitTargetPercent === null
          ? "non sourcé"
          : `${formatSignedMoney((challenge.accountSize * objectives.profitTargetPercent) / 100)} (${objectives.profitTargetPercent} %)`}
      </Row>
      <Row label="Jours de trading minimum" tone={objectives.minTradingDays === null ? "text-muted-foreground" : "text-foreground"}>
        {objectives.minTradingDays ?? "non sourcé"}
      </Row>
    </>
  );
}
