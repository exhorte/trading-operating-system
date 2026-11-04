"use client";

import { Landmark } from "lucide-react";
import { useApi } from "@/lib/api/use-api";
import type { AccountIdentification, EffectiveRiskPolicy, ProviderLossState } from "@/lib/api/generated";
import {
  confidenceView,
  limitProvenance,
  limitValue,
  lossLines,
  lossStatusLabel,
  lossTone,
  modeLabel,
  reasonText,
} from "@/lib/accounts/provider-view";
import { Callout } from "@/components/ui/callout";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

const POLL_MS = 15_000;

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function Identification({ identification, leverage, currency }: { identification: AccountIdentification; leverage: number | null; currency: string }) {
  const confidence = confidenceView(identification.providerConfidence);
  return (
    <section className="flex flex-col gap-3" aria-label="Identification du compte">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Qui est ce compte</h3>
        <StatusPill tone={identification.executable ? "profit" : "loss"}>
          {identification.executable ? "Exécutable" : "Non exécutable"}
        </StatusPill>
        <StatusPill tone={confidence.tone}>{confidence.label}</StatusPill>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Fact label="Fournisseur (terminal)">{identification.provider ?? "non identifié"}</Fact>
        <Fact label="Produit du porteur">{identification.brokerProduct}</Fact>
        <Fact label="Règles appliquées">
          {identification.rulesProduct}
          {identification.rulesRehearsal ? " (répétées)" : ""}
        </Fact>
        <Fact label="Mode">{modeLabel(identification.accountMode)}</Fact>
        <Fact label="Levier">{leverage === null ? "inconnu" : `1:${leverage}`}</Fact>
        <Fact label="Devise">{currency}</Fact>
        <Fact label="Jeu de règles">{identification.ruleSetId ?? "aucun"}</Fact>
      </dl>
      {identification.blockers.length > 0 && (
        <ul className="flex flex-col gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
          {identification.blockers.map((blocker) => (
            <li key={blocker}>
              <span className="font-medium">{reasonText(blocker)}</span>{" "}
              <code className="text-xs text-muted-foreground">{blocker}</code>
            </li>
          ))}
        </ul>
      )}
      {identification.conflicts.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
          {identification.conflicts.map((conflict) => (
            <li key={conflict}>{conflict}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Floors({ state, currency }: { state: ProviderLossState; currency: string }) {
  if (state.status === "not_applicable") {
    return (
      <section className="flex flex-col gap-1" aria-label="Planchers de perte du fournisseur">
        <h3 className="text-sm font-semibold">Planchers de perte du fournisseur</h3>
        <p className="text-sm text-muted-foreground">Ce produit n&apos;impose aucun plancher : seules tes règles s&apos;appliquent.</p>
      </section>
    );
  }
  return (
    <section className="flex flex-col gap-3" aria-label="Planchers de perte du fournisseur">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Planchers de perte du fournisseur</h3>
        <StatusPill tone={lossTone(state)}>{lossStatusLabel(state)}</StatusPill>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[28rem] text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-3 font-medium">Limite</th>
              <th className="py-1 pr-3 text-right font-medium">Solde de référence</th>
              <th className="py-1 pr-3 text-right font-medium">Plancher d&apos;équité</th>
              <th className="py-1 text-right font-medium">Marge restante</th>
            </tr>
          </thead>
          <tbody>
            {lossLines(state, currency).map((line) => (
              <tr key={line.label} className="border-t">
                <td className="py-1.5 pr-3">{line.label}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{line.reference}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{line.floor}</td>
                <td className="py-1.5 text-right tabular-nums">{line.margin}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {state.reasons.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {state.reasons.map((reason) => (
            <li key={reason}>
              {reasonText(reason)} <code className="text-xs text-muted-foreground">{reason}</code>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        Le plancher se construit sur le solde enregistré à 00:00 ({state.timezone}) ; c&apos;est l&apos;équité qui est testée. La référence est écrite une fois :
        un redémarrage ne la remet pas à zéro.
      </p>
    </section>
  );
}

function Policy({ policy }: { policy: EffectiveRiskPolicy }) {
  return (
    <section className="flex flex-col gap-3" aria-label="Politique de risque effective">
      <h3 className="text-sm font-semibold">Politique de risque effective — la plus stricte l&apos;emporte</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-3 font-medium">Limite</th>
              <th className="py-1 pr-3 text-right font-medium">Valeur</th>
              <th className="py-1 font-medium">D&apos;où elle vient</th>
            </tr>
          </thead>
          <tbody>
            {policy.limits.map((limit) => (
              <tr key={limit.key} className="border-t align-top">
                <td className="py-1.5 pr-3">{limit.label}</td>
                <td className="py-1.5 pr-3 text-right font-medium tabular-nums">{limitValue(limit)}</td>
                <td className="py-1.5 text-muted-foreground [overflow-wrap:anywhere]">
                  {limitProvenance(limit)}
                  {limit.enforcedBy === null && " · affichée, non appliquée"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="flex flex-col gap-1.5 text-sm">
        {policy.restrictions.map((restriction) => (
          <li key={restriction.key} className="flex flex-wrap items-baseline gap-x-2">
            <StatusPill tone={restriction.informational ? "muted" : restriction.active ? "warning" : "muted"}>
              {restriction.informational ? "information" : restriction.active ? "active" : "sans objet"}
            </StatusPill>
            <span className="font-medium">{restriction.label}</span>
            <span className="text-muted-foreground [overflow-wrap:anywhere]">{restriction.detail}</span>
          </li>
        ))}
      </ul>
      {(policy.notSourced.length > 0 || policy.needsReview.length > 0) && (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">Ce qui n&apos;est pas sourcé, ce qui demande relecture</summary>
          <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-muted-foreground">
            {policy.notSourced.map((item) => (
              <li key={`n-${item}`}>Non sourcé : {item}</li>
            ))}
            {policy.needsReview.map((item) => (
              <li key={`r-${item}`}>À relire : {item}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/**
 * « Environnement et règles du fournisseur » (ADR 0036) — what the core identified about the active account, which provider's contract
 * applies, the floors that contract draws under the equity, and every limit with the source that binds it. The core decides and explains;
 * nothing here re-derives a rule. A refusal is shown with its reason, never as a bare red value.
 */
export function ProviderRulesCard({ accountId }: { accountId: string }) {
  const args = { path: { account_id: accountId } } as const;
  const profile = useApi("accounts_profile", args, { pollMs: POLL_MS });
  const policy = useApi("accounts_effective_policy", args, { pollMs: POLL_MS });
  const loss = useApi("accounts_provider_loss", args, { pollMs: POLL_MS });
  const error = profile.error ?? policy.error ?? loss.error;

  return (
    <Panel
      title="Environnement et règles du fournisseur"
      description="ce que le cœur a identifié, et ce qui s'applique réellement"
      icon={Landmark}
    >
      <div className="flex flex-col gap-6">
        {error && (
          <Callout title="Lecture incomplète" variant="warning">
            {error.message}
          </Callout>
        )}
        {profile.data ? (
          <Identification
            identification={profile.data.identification}
            leverage={profile.data.leverage}
            currency={profile.data.currency}
          />
        ) : (
          !profile.error && <Skeleton className="h-32" />
        )}
        {loss.data && profile.data && <Floors state={loss.data} currency={profile.data.currency} />}
        {policy.data ? <Policy policy={policy.data} /> : !policy.error && <Skeleton className="h-48" />}
        {profile.data?.commission && (
          <p className="text-sm text-muted-foreground">
            <span className="font-medium text-foreground">Commission</span> — {profile.data.commission.source} :{" "}
            {profile.data.commission.detail}
          </p>
        )}
      </div>
    </Panel>
  );
}
