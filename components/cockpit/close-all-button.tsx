"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CircleX, Loader2, RefreshCw, TriangleAlert } from "lucide-react";
import { cn } from "cn";
import { call } from "@/lib/api/client";
import type { CloseAllPreview, CloseAllReport } from "@/lib/api/generated";
import { useCockpit } from "@/lib/realtime/provider";
import { formatQuote, formatSignedMoney } from "@/lib/format";
import {
  actionText,
  BUTTON_LABEL,
  CONFIRM_LABEL,
  CONFIRMATION,
  headline,
  ITEM_LABELS,
  itemTone,
  nextStep,
  progressLine,
  reasonLine,
  reasonText,
  summary,
} from "@/lib/cockpit/close-all";
import { REAL_ACCOUNT_BANNER } from "@/lib/cockpit/startup";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { StatusPill } from "@/components/ui/status-pill";

const POLL_MS = 1000;

type Phase =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "review"; preview: CloseAllPreview }
  | { kind: "sending"; preview: CloseAllPreview }
  | { kind: "running"; preview: CloseAllPreview; report: CloseAllReport }
  | { kind: "error"; message: string };

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : "Opération impossible.");

/**
 * « FERMER TOUTES LES POSITIONS » (ADR 0034) — the one button that closes what is open on the selected account, through the path
 * that already exists (cockpit → core → execution engine → agent → MT5), in every mode including HALTED.
 *
 * Opening the dialog sends **nothing**: it reads the account fresh and shows what would be closed. Only the second, explicit button
 * sends, with a batch id the core gave in the preview (a double click cannot close twice). The result is never called a success on the
 * agent's word: the core says COMPLETE only once MT5 no longer shows the position and a reconciliation has run since.
 */
export function CloseAllButton({ size = "default", className }: { size?: "default" | "sm" | "lg"; className?: string }) {
  const { activeAccountId, positions } = useCockpit();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [includeOrders, setIncludeOrders] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadPreview = useCallback(async () => {
    if (activeAccountId === null) {
      return;
    }
    setPhase({ kind: "loading" });
    setIncludeOrders(false);
    try {
      const preview = await call("execution_close_all_preview", { query: { accountId: activeAccountId } });
      setPhase({ kind: "review", preview });
    } catch (error) {
      setPhase({ kind: "error", message: messageOf(error) });
    }
  }, [activeAccountId]);

  function openDialog() {
    setOpen(true);
    // A batch in flight (or just finished) is shown as it is; a fresh gesture starts from a fresh read.
    if (phase.kind === "idle" || phase.kind === "error" || phase.kind === "review") {
      void loadPreview();
    }
  }

  async function confirm(preview: CloseAllPreview) {
    if (activeAccountId === null) {
      return;
    }
    setPhase({ kind: "sending", preview });
    try {
      const report = await call("execution_close_all", {
        body: {
          accountId: activeAccountId,
          batchId: preview.batchId,
          positionIds: preview.positions.map((p) => p.positionId),
          includePendingOrders: includeOrders,
          orderIds: includeOrders ? preview.pendingOrders.map((o) => o.orderId) : [],
          confirmation: CONFIRMATION,
        },
      });
      setPhase({ kind: "running", preview, report });
    } catch (error) {
      setPhase({ kind: "error", message: messageOf(error) });
    }
  }

  const verify = useCallback(async (preview: CloseAllPreview, batchId: string) => {
    setVerifying(true);
    try {
      const report = await call("execution_close_all_verify", {
        path: { batch_id: batchId },
        query: { accountId: preview.account.accountId },
      });
      setPhase({ kind: "running", preview, report });
    } catch (error) {
      setPhase({ kind: "error", message: messageOf(error) });
    } finally {
      setVerifying(false);
    }
  }, []);

  // Follow the batch: poll while commands move, ask the core to check with MT5 once they have settled, stop when it is final.
  useEffect(() => {
    if (phase.kind !== "running" || phase.report.final) {
      return;
    }
    const { preview, report } = phase;
    const step = nextStep(report);
    timer.current = setTimeout(async () => {
      try {
        const next =
          step === "verify"
            ? await call("execution_close_all_verify", {
                path: { batch_id: report.batchId },
                query: { accountId: preview.account.accountId },
              })
            : await call("execution_close_all_report", {
                path: { batch_id: report.batchId },
                query: { accountId: preview.account.accountId },
              });
        setPhase({ kind: "running", preview, report: next });
      } catch (error) {
        setPhase({ kind: "error", message: messageOf(error) });
      }
    }, POLL_MS);
    return () => {
      if (timer.current !== null) {
        clearTimeout(timer.current);
        timer.current = null;
      }
    };
  }, [phase]);

  const finished = phase.kind === "running" && phase.report.final;
  const busy = phase.kind === "sending" || (phase.kind === "running" && !phase.report.final);

  return (
    <>
      <Button
        type="button"
        variant="destructive"
        size={size}
        className={cn("font-semibold tracking-wide", className)}
        disabled={activeAccountId === null}
        onClick={openDialog}
        title={
          activeAccountId === null
            ? "Aucun compte actif : rien à fermer"
            : "Ouvre la confirmation. Rien n'est fermé tant que vous n'avez pas confirmé."
        }
      >
        <CircleX aria-hidden="true" />
        {BUTTON_LABEL}
        {positions.length > 0 && (
          <span className="ml-1 rounded-full bg-background/20 px-1.5 text-xs tabular-nums">{positions.length}</span>
        )}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent aria-describedby="close-all-description">
          <DialogHeader>
            <DialogTitle>{BUTTON_LABEL}</DialogTitle>
            <DialogDescription id="close-all-description">
              Ferme les positions ouvertes du compte sélectionné, quel que soit le symbole ou la stratégie. Fonctionne dans tous les
              modes, y compris à l&apos;arrêt (HALTED).
            </DialogDescription>
          </DialogHeader>

          {phase.kind === "loading" && (
            <p className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              Lecture du compte chez MT5…
            </p>
          )}

          {phase.kind === "error" && (
            <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
              <p className="font-medium">L&apos;opération a échoué.</p>
              <p className="mt-1">{phase.message}</p>
              <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => void loadPreview()}>
                Relire le compte
              </Button>
            </div>
          )}

          {(phase.kind === "review" || phase.kind === "sending") && (
            <Review
              preview={phase.preview}
              includeOrders={includeOrders}
              onIncludeOrders={setIncludeOrders}
              sending={phase.kind === "sending"}
              onConfirm={() => void confirm(phase.preview)}
              onCancel={() => setOpen(false)}
            />
          )}

          {phase.kind === "running" && (
            <Progression
              report={phase.report}
              preview={phase.preview}
              verifying={verifying}
              onVerify={() => void verify(phase.preview, phase.report.batchId)}
            />
          )}

          {(finished || phase.kind === "error") && (
            <DialogFooter>
              {finished && (
                <Button type="button" variant="outline" onClick={() => void loadPreview()}>
                  Nouvelle fermeture
                </Button>
              )}
              <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
                Fermer cette fenêtre
              </Button>
            </DialogFooter>
          )}
          {busy && phase.kind === "running" && (
            <p className="text-xs text-muted-foreground">
              Vous pouvez fermer cette fenêtre : le lot continue dans le cœur, et le bouton le montrera à la réouverture.
            </p>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

// ----------------------------------------------------------------------------------------------------- the confirmation

function Review({
  preview,
  includeOrders,
  onIncludeOrders,
  sending,
  onConfirm,
  onCancel,
}: {
  preview: CloseAllPreview;
  includeOrders: boolean;
  onIncludeOrders: (value: boolean) => void;
  sending: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { account } = preview;
  const real = account.environment === "LIVE";
  const nothing = preview.positions.length === 0 && (!includeOrders || preview.pendingOrders.length === 0);
  return (
    <div className="flex flex-col gap-4">
      {real && (
        <p role="alert" className="rounded-lg bg-destructive px-4 py-2.5 text-sm font-semibold text-destructive-foreground">
          {REAL_ACCOUNT_BANNER}
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg border p-4 text-sm sm:grid-cols-4">
        <Fact label="Compte" value={account.name} />
        <Fact label="Fournisseur" value={account.provider} />
        <Fact label="Numéro" value={account.loginMasked} />
        <Fact
          label="Environnement"
          value={<StatusPill tone={real ? "loss" : "info"}>{real ? "Réel" : account.environment === "DEMO" ? "Démo" : "Simulé"}</StatusPill>}
        />
        <Fact label="Serveur" value={account.server} />
        <Fact label="Mode" value={account.planMode} />
        <Fact label="Balance" value={account.balance === null ? "—" : `${account.balance.toFixed(2)} ${account.currency}`} />
        <Fact label="Equity" value={account.equity === null ? "—" : `${account.equity.toFixed(2)} ${account.currency}`} />
      </dl>

      {preview.blockers.length > 0 && (
        <ul role="alert" className="flex flex-col gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {preview.blockers.map((b) => (
            <li key={b.code} className="flex gap-2">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {reasonLine(b, "blocker")}
            </li>
          ))}
        </ul>
      )}

      <div>
        <p className="mb-2 text-sm font-medium">
          {preview.positions.length === 0
            ? "Aucune position ouverte."
            : `${preview.positions.length} position${preview.positions.length > 1 ? "s" : ""} ouverte${preview.positions.length > 1 ? "s" : ""}`}
          {preview.positions.length > 0 && (
            <span className={cn("ml-2 tabular-nums", preview.totalUnrealizedPnl >= 0 ? "text-success" : "text-destructive")}>
              P&amp;L latent {formatSignedMoney(preview.totalUnrealizedPnl, account.currency)}
            </span>
          )}
        </p>
        {preview.positions.length > 0 && (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-left text-sm">
              <thead className="bg-muted/50 text-xs text-muted-foreground">
                <tr>
                  {["Symbole", "Sens", "Volume", "Entrée", "SL", "TP", "P&L latent"].map((h) => (
                    <th key={h} className="px-3 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.positions.map((p) => (
                  <tr key={p.positionId} className="border-t">
                    <td className="px-3 py-2 font-medium">
                      {p.symbol}
                      {!p.closable && (
                        <span className="ml-2 text-xs font-normal text-warning" title={p.notClosableReason ?? undefined}>
                          non fermable par l&apos;agent
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">{p.side === "buy" ? "Achat" : "Vente"}</td>
                    <td className="px-3 py-2 tabular-nums">{p.volume.toFixed(2)}</td>
                    <td className="px-3 py-2 tabular-nums">{formatQuote(p.entryPrice)}</td>
                    <td className="px-3 py-2 tabular-nums text-muted-foreground">{p.stopLoss > 0 ? formatQuote(p.stopLoss) : "—"}</td>
                    <td className="px-3 py-2 tabular-nums text-muted-foreground">{p.takeProfit > 0 ? formatQuote(p.takeProfit) : "—"}</td>
                    <td className={cn("px-3 py-2 tabular-nums", p.unrealizedPnl >= 0 ? "text-success" : "text-destructive")}>
                      {formatSignedMoney(p.unrealizedPnl, account.currency)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {preview.pendingOrders.length > 0 && (
        <div className="rounded-lg border p-4">
          <p className="text-sm font-medium">
            {preview.pendingOrders.length} ordre{preview.pendingOrders.length > 1 ? "s" : ""} en attente
            <span className="font-normal text-muted-foreground">
              {" "}
              — {preview.pendingOrders.map((o) => `${o.symbol} ${o.side === "buy" ? "achat" : "vente"} ${o.volume.toFixed(2)} @ ${formatQuote(o.price)}`).join(" · ")}
            </span>
          </p>
          <label className="mt-2 flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-current"
              checked={includeOrders}
              onChange={(event) => onIncludeOrders(event.target.checked)}
            />
            Annuler également tous les ordres en attente
          </label>
          <p className="mt-1 text-xs text-muted-foreground">
            Annuler un ordre en attente n&apos;est pas fermer une position : ce sont deux commandes distinctes.
          </p>
        </div>
      )}

      <ul className="flex flex-col gap-1.5 text-sm text-muted-foreground">
        {preview.warnings.map((w) => (
          <li key={w.code} className={cn("flex gap-2", w.code === "real_account" && "hidden")}>
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
            {reasonLine(w, "warning")}
          </li>
        ))}
      </ul>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel} disabled={sending}>
          Annuler — ne rien fermer
        </Button>
        <Button
          type="button"
          variant="destructive"
          onClick={onConfirm}
          disabled={sending || !preview.canExecute || nothing}
          className="font-semibold"
        >
          {sending && <Loader2 className="animate-spin" aria-hidden="true" />}
          {CONFIRM_LABEL}
        </Button>
      </DialogFooter>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate font-medium">{value}</dd>
    </div>
  );
}

// ----------------------------------------------------------------------------------------------------- the progression and the report

function Progression({
  report,
  preview,
  verifying,
  onVerify,
}: {
  report: CloseAllReport;
  preview: CloseAllPreview;
  verifying: boolean;
  onVerify: () => void;
}) {
  const totals = summary(report);
  const settled = report.items.filter((i) => !["IN_PROGRESS", "VERIFYING"].includes(i.status)).length;
  const percent = report.items.length === 0 ? 100 : Math.round((settled / report.items.length) * 100);
  const tone = report.status === "COMPLETE" ? "profit" : report.status === "INCOMPLETE" ? "loss" : "info";
  return (
    <div className="flex flex-col gap-4" aria-live="polite">
      <div>
        <p className="flex items-center gap-2 text-base font-semibold">
          {!report.final && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
          {headline(report.status)}
          <StatusPill tone={tone}>{report.status}</StatusPill>
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{progressLine(report)}</p>
        <Progress value={percent} className="mt-3" />
      </div>

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Cible</th>
              <th className="px-3 py-2 font-medium">Sens</th>
              <th className="px-3 py-2 font-medium">Volume</th>
              <th className="px-3 py-2 font-medium">État</th>
              <th className="px-3 py-2 font-medium">Motif</th>
            </tr>
          </thead>
          <tbody>
            {report.items.map((item) => (
              <tr key={`${item.target}-${item.targetId}`} className="border-t align-top">
                <td className="px-3 py-2 font-medium">
                  {item.symbol === "?" ? `#${item.targetId}` : item.symbol}
                  <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                    {item.target === "order" ? "ordre en attente" : "position"}
                  </span>
                </td>
                <td className="px-3 py-2">{item.side === null ? "—" : item.side === "buy" ? "Achat" : "Vente"}</td>
                <td className="px-3 py-2 tabular-nums">{item.volume === null ? "—" : item.volume.toFixed(2)}</td>
                <td className="px-3 py-2">
                  <StatusPill tone={itemTone(item.status)}>{ITEM_LABELS[item.status]}</StatusPill>
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                  {item.rejectCode || ["UNKNOWN", "SIMULATED", "MISMATCH", "NOT_CLOSABLE"].includes(item.status)
                    ? reasonText(item.rejectCode ?? item.status, item.detail)
                    : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {report.final && (
        <dl className="grid grid-cols-3 gap-3 rounded-lg border p-4 text-sm">
          <Fact label="Positions fermées" value={<span className="text-lg tabular-nums">{totals.closed}</span>} />
          <Fact
            label="Positions encore ouvertes"
            value={<span className={cn("text-lg tabular-nums", totals.stillOpen > 0 && "text-destructive")}>{totals.stillOpen}</span>}
          />
          <Fact
            label="Refusées ou inconnues"
            value={<span className={cn("text-lg tabular-nums", totals.rejectedOrUnknown > 0 && "text-destructive")}>{totals.rejectedOrUnknown}</span>}
          />
        </dl>
      )}

      {report.failures.length > 0 && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <p className="font-medium text-destructive">Motifs des échecs</p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {report.failures.map((f) => (
              <li key={f.reason}>
                <span className="font-medium">{f.count} ×</span> {reasonText(f.reason, f.detail)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.actions.length > 0 && (
        <div role="note" className="rounded-lg border border-warning/30 bg-warning/5 p-4 text-sm">
          <p className="font-medium">Action recommandée</p>
          <ul className="mt-1.5 flex flex-col gap-1 text-muted-foreground">
            {report.actions.map((a) => (
              <li key={a}>{actionText(a)}</li>
            ))}
          </ul>
        </div>
      )}

      {report.otherOpenPositions.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Hors de ce lot, encore ouvertes chez MT5 : {report.otherOpenPositions.map((id) => `#${id}`).join(", ")}.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" size="sm" onClick={onVerify} disabled={verifying}>
          <RefreshCw className={cn(verifying && "animate-spin")} aria-hidden="true" />
          Vérifier avec MT5
        </Button>
        <p className="text-xs text-muted-foreground">
          Lit le terminal et réconcilie la base avec le courtier (lecture seule : rien n&apos;est renvoyé). Compte {preview.account.loginMasked}.
        </p>
      </div>
    </div>
  );
}
