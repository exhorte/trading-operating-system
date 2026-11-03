import { StartupScreen } from "@/components/cockpit/startup-panel";
import { PageHeader } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";

/**
 * Démarrage — « le système est-il en état de prendre une position, et sinon qu'est-ce qui bloque ».
 *
 * Three gestures live here and stay apart (ADR 0034): starting the trading system (verifies, reconciles, climbs to OBSERVE at
 * most), stopping (entries, engines — never the positions), and authorising automatic trading (its own card, one rung, every
 * condition green at that instant). Closing every position is its own button, available on every screen that shows positions.
 */
export default function StartupPage() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeader screen={screenAt("/demarrage")} />
      <StartupScreen />
    </div>
  );
}
