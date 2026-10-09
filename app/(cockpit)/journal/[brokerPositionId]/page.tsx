"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { LucideIcon } from "lucide-react";
import { ArrowLeft, Compass, FileText, Flag, Send, ShieldCheck } from "lucide-react";
import type { TradeFile } from "@/lib/api/generated";
import { isApiError } from "@/lib/api/client";
import { useApi } from "@/lib/api/use-api";
import { COMMAND_STATE_TONES } from "@/lib/cockpit/command-state";
import { VIOLATION_LABELS } from "@/lib/compliance/labels";
import { formatDateTime, formatQuote, formatSignedMoney } from "@/lib/format";
import { useCockpit } from "@/lib/realtime/provider";
import { TradeFileMetrics } from "@/components/journal/trade-file-metrics";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { EmptyState } from "@/components/ui/empty-state";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { SplitLayout } from "@/components/ui/split-layout";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

function Facts({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt>{label}</dt>
          <dd className="tnum text-right text-foreground">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Step({ icon: Icon, title, pill, children }: { icon: LucideIcon; title: string; pill?: ReactNode; children: ReactNode }) {
  return (
    <li className="border-t py-4 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Icon className="size-4 text-muted-foreground" aria-hidden="true" />
          {title}
        </span>
        {pill}
      </div>
      <div className="mt-2 text-sm leading-snug text-muted-foreground">{children}</div>
    </li>
  );
}

function IntentStep({ file }: { file: TradeFile }) {
  const intent = file.intent;
  return (
    <Step icon={Compass} title="Intention" pill={intent ? <StatusPill tone="info">{intent.strategyId}</StatusPill> : undefined}>
      {intent ? (
        <>
          <Facts
            rows={[
              ["Stratégie", `${intent.strategyId} v${intent.strategyVersion}`],
              ["Sens", intent.side === "buy" ? "Achat" : "Vente"],
              ["Entrée prévue", `${intent.orderType} · ${formatQuote(intent.entryPrice)}`],
              ["Stop / objectif prévus", `${formatQuote(intent.stopLoss)} / ${formatQuote(intent.takeProfit)}`],
              ["Formulée le", formatDateTime(intent.createdAt)],
            ]}
          />
          {intent.rationale && <p className="mt-2">{intent.rationale}</p>}
        </>
      ) : (
        "non enregistrée"
      )}
    </Step>
  );
}

function DecisionStep({ file }: { file: TradeFile }) {
  const decision = file.decision;
  return (
    <Step
      icon={ShieldCheck}
      title="Décision de risque"
      pill={
        decision ? <StatusPill tone={decision.approved ? "profit" : "loss"}>{decision.approved ? "approuvée" : "refusée"}</StatusPill> : undefined
      }
    >
      {decision ? (
        <>
          <Facts
            rows={[
              ["Volume approuvé", decision.approvedVolume === null ? "—" : `${decision.approvedVolume.toFixed(2)} lot`],
              ["Risque au stop", decision.sizing ? formatSignedMoney(-decision.sizing.riskAtStop) : "—"],
              ["Décidée le", formatDateTime(decision.decidedAt)],
            ]}
          />
          {decision.reasons.length > 0 && <p className="mt-2">{decision.reasons.join(" · ")}</p>}
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Contrôles du moteur de risque">
            {decision.checks.map((check) => (
              <li key={check.checkId} title={check.detail}>
                <StatusPill tone={check.ok ? "profit" : "loss"}>{check.label}</StatusPill>
              </li>
            ))}
          </ul>
        </>
      ) : (
        "non enregistrée"
      )}
    </Step>
  );
}

function CommandStep({ file }: { file: TradeFile }) {
  const command = file.command;
  return (
    <Step
      icon={Send}
      title="Commande"
      pill={command ? <StatusPill tone={COMMAND_STATE_TONES[command.state] as PillTone}>{command.state}</StatusPill> : undefined}
    >
      {command ? (
        <>
          <Facts
            rows={[
              ["Commande", command.request.commandId],
              ["Route / mode", `${command.route} · ${command.mode}`],
              ["Créée le", formatDateTime(command.createdAt)],
              ["Exécution", command.averagePrice === null ? "—" : `${command.filledVolume ?? "?"} lot @ ${formatQuote(command.averagePrice)}`],
            ]}
          />
          {command.detail && <p className="mt-2">{command.detail}</p>}
        </>
      ) : (
        "non enregistrée"
      )}
    </Step>
  );
}

function OutcomeStep({ file }: { file: TradeFile }) {
  const trade = file.trade;
  return (
    <Step
      icon={Flag}
      title="Résultat"
      pill={<StatusPill tone={file.status === "open" ? "info" : "muted"}>{file.status === "open" ? "ouverte" : "clôturée"}</StatusPill>}
    >
      {trade ? (
        <>
          <Facts
            rows={[
              ["Ouverture", trade.openedAt ? formatDateTime(trade.openedAt) : "non observée"],
              ["Clôture", formatDateTime(trade.closedAt)],
              ["Volume", `${trade.volume.toFixed(2)} lot`],
              ["Résultat réalisé", formatSignedMoney(trade.realizedPnl)],
              ["R", file.rMultiple === null ? "inconnu" : file.rMultiple.toFixed(2)],
            ]}
          />
          {file.violations.length === 0 ? (
            <p className="mt-2">Aucun manquement détectable aux règles du compte.</p>
          ) : (
            <ul className="mt-2 flex flex-col gap-1.5">
              {file.violations.map((violation) => (
                <li key={violation.type}>
                  <StatusPill tone="loss">{VIOLATION_LABELS[violation.type]}</StatusPill>
                  <span className="ml-2">{violation.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        "La position est encore ouverte : pas de résultat."
      )}
    </Step>
  );
}

/**
 * The file of one trade — numbers only (ADR 0018). It used to be a rendered chart of the moment; there is no image of any kind
 * any more, and no chart behind these figures: what is kept is what was recorded when the position opened and when it closed,
 * and the chain that led to it — Intention → Décision de risque → Commande → Résultat (ADR 0007). A position nobody commanded
 * (opened by hand in MT5) says so instead of inventing a chain.
 *
 * Composition (ADR 0017): the chain on the left, the recorded levels in the dark panel on the right (first on mobile). An
 * unknown position is an empty state — nothing was recorded — while a failed read is a warning: the two must not look alike.
 */
export default function TradeFilePage() {
  const params = useParams<{ brokerPositionId: string }>();
  const { activeAccountId: accountId } = useCockpit();

  const { data: file, error } = useApi(
    "journal_trade_file",
    accountId ? { path: { broker_position_id: params.brokerPositionId }, query: { accountId } } : null,
  );

  const header = (
    <PageHeader
      title="Dossier du trade"
      subtitle={`Position ${params.brokerPositionId}`}
      icon={FileText}
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/journal">
            <ArrowLeft aria-hidden="true" />
            Retour au journal
          </Link>
        </Button>
      }
    />
  );

  const unknown = error !== null && isApiError(error) && error.code === "position_not_found";

  if (!accountId || (!file && !error)) {
    return (
      <div className="flex flex-col gap-10">
        <SplitLayout
          main={
            <>
              {header}
              <Skeleton className="h-96 rounded-xl" />
            </>
          }
          aside={
            <>
              <Skeleton className="h-[72px] rounded-xl" />
              <Skeleton className="h-[420px] rounded-xl" />
            </>
          }
        />
      </div>
    );
  }

  if (error && !unknown) {
    return (
      <div className="flex flex-col gap-10">
        {header}
        <Callout title="Dossier illisible" variant="warning">
          {error.message}
        </Callout>
      </div>
    );
  }

  if (unknown || !file) {
    return (
      <div className="flex flex-col gap-10">
        {header}
        <EmptyState
          icon={FileText}
          title="Aucune trace de cette position"
          description="Le système n'a jamais vu cette position : ni ouverture observée, ni commande, ni trade clôturé."
          hint={`Position ${params.brokerPositionId}`}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        stickyAside
        asideFirstOnMobile
        main={
          <>
            {header}
            <Panel
              title="De l'intention au résultat"
              description={file.manual ? "ouverte à la main dans MT5" : "ce que le système a décidé, puis ce qui s'est passé"}
              icon={FileText}
            >
              {file.manual ? (
                <p className="text-sm leading-snug text-muted-foreground">
                  Cette position a été ouverte à la main dans MT5 : aucune intention, aucune décision de risque ni aucune
                  commande n&apos;existe pour elle. Les chiffres sont ceux que le terminal a rapportés, enregistrés à
                  l&apos;ouverture et à la clôture.
                </p>
              ) : (
                <ol className="flex flex-col">
                  <IntentStep file={file} />
                  <DecisionStep file={file} />
                  <CommandStep file={file} />
                  <OutcomeStep file={file} />
                </ol>
              )}
              {file.manual && file.trade && (
                <ol className="mt-4 flex flex-col border-t pt-4">
                  <OutcomeStep file={file} />
                </ol>
              )}
            </Panel>
          </>
        }
        aside={<TradeFileMetrics file={file} />}
      />
      <Callout title="Important">
        Rien ici n&apos;est une image : ce sont les prix enregistrés au moment réel de l&apos;ouverture et de la clôture
        (ADR 0018). Un stop ou un objectif « non posé » veut dire que MT5 a renvoyé 0 pour un niveau qui n&apos;a jamais
        été attaché — pas un niveau à zéro.
      </Callout>
    </div>
  );
}
