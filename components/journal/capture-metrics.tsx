import { Camera, LogIn, LogOut, OctagonX, Target } from "lucide-react";
import { formatQuote } from "@/lib/format";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";
import { StatusPill } from "@/components/ui/status-pill";

/** The levels recorded with a capture. `null` = not set / not captured — never a level at zero. */
export interface CaptureLevels {
  symbol: string;
  timeframe: string;
  entry: number | null;
  stop: number | null;
  target: number | null;
  exit: number | null;
}

const price = (value: number | null) => (value === null ? "—" : formatQuote(value));

/**
 * The prices frozen with a trade's capture, in the dark panel (ADR 0017).
 * They are facts written when the position opened and when it closed — the
 * chart beside them is rendered from the same rows, so the two cannot differ.
 */
export function CaptureMetrics({ levels }: { levels: CaptureLevels }) {
  return (
    <>
      <HighlightBar
        icon={Camera}
        value={levels.symbol}
        label={`capture · ${levels.timeframe}`}
        aside={
          <StatusPill tone="muted" onPanel>
            {levels.exit === null ? "entrée seule" : "entrée et sortie"}
          </StatusPill>
        }
      />
      <MetricPanel>
        <MetricPanelItem
          label="Entrée"
          value={price(levels.entry)}
          hint="prix d'ouverture enregistré"
          icon={LogIn}
          solidIcon
        />
        <MetricPanelItem
          label="Stop"
          value={price(levels.stop)}
          hint={levels.stop === null ? "aucun stop posé : MT5 renvoie 0 pour « non posé »" : "niveau posé à l'ouverture"}
          icon={OctagonX}
        />
        <MetricPanelItem
          label="Objectif"
          value={price(levels.target)}
          hint={levels.target === null ? "aucun objectif posé" : "niveau posé à l'ouverture"}
          icon={Target}
        />
        <MetricPanelItem
          label="Sortie"
          value={price(levels.exit)}
          hint={levels.exit === null ? "pas de capture de sortie" : "prix de clôture enregistré"}
          icon={LogOut}
        />
      </MetricPanel>
    </>
  );
}
