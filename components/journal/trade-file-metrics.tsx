import { Coins, LogIn, LogOut, OctagonX, Percent, Target } from "lucide-react";
import type { TradeFile } from "@/lib/api/generated";
import { formatQuote, formatSignedMoney } from "@/lib/format";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";
import { StatusPill } from "@/components/ui/status-pill";

/** MT5 reports 0 for a stop or a target that was never attached: that is « not set », not a level at zero. */
const level = (value: number | null | undefined) => (value === null || value === undefined || value <= 0 ? null : value);

const price = (value: number | null) => (value === null ? "—" : formatQuote(value));

/**
 * The numbers recorded for a trade, in the dark panel (ADR 0017). They are facts written when the position opened and when it
 * closed — there is no image and no chart behind them (ADR 0018): the prices, the stop, the target, the result.
 */
export function TradeFileMetrics({ file }: { file: TradeFile }) {
  const entryRow = file.entryCapture;
  const trade = file.trade;
  const symbol = trade?.symbol ?? entryRow?.symbol ?? "—";
  const entry = trade?.entryPrice ?? entryRow?.entryPrice ?? null;
  const stop = level(trade?.stopLoss ?? entryRow?.stopLoss);
  const target = level(entryRow?.takeProfit);
  const exit = trade?.exitPrice ?? file.exitCapture?.exitPrice ?? null;
  const pnl = trade?.realizedPnl ?? null;

  return (
    <>
      <HighlightBar
        icon={Coins}
        value={symbol}
        label={`position ${file.brokerPositionId}`}
        aside={
          <StatusPill tone={file.status === "open" ? "info" : "muted"} onPanel>
            {file.status === "open" ? "ouverte" : "clôturée"}
          </StatusPill>
        }
      />
      <MetricPanel>
        <MetricPanelItem
          label="Entrée"
          value={price(entry)}
          hint={entry === null ? "prix d'ouverture non enregistré" : "prix d'ouverture enregistré"}
          icon={LogIn}
          solidIcon
        />
        <MetricPanelItem
          label="Stop"
          value={price(stop)}
          hint={stop === null ? "aucun stop posé : MT5 renvoie 0 pour « non posé »" : "niveau posé à l'ouverture"}
          icon={OctagonX}
        />
        <MetricPanelItem
          label="Objectif"
          value={price(target)}
          hint={target === null ? "aucun objectif posé" : "niveau posé à l'ouverture"}
          icon={Target}
        />
        <MetricPanelItem
          label="Sortie"
          value={price(exit)}
          hint={exit === null ? "position encore ouverte" : "prix de clôture enregistré"}
          icon={LogOut}
        />
        <MetricPanelItem
          label="Résultat réalisé"
          value={pnl === null ? "—" : formatSignedMoney(pnl)}
          tone={pnl === null ? undefined : pnl >= 0 ? "success" : "destructive"}
          hint={
            file.rMultiple === null
              ? "R inconnu : ni l'entrée ni le stop ne sont enregistrés"
              : `${file.rMultiple >= 0 ? "+" : ""}${file.rMultiple.toFixed(2)} R`
          }
          icon={Percent}
        />
      </MetricPanel>
    </>
  );
}
