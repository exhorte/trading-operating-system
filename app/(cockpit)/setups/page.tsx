import { SetupsScreen } from "@/components/cockpit/setups-screen";

/**
 * EA-02 — the instrument of measurement (S01, "Critère de réussite"). Not
 * a signal screen: no button here sends anything anywhere. See
 * context/product/tools/EA-02-observe-taux-accord.md. The screen owns its
 * fetches (components/cockpit/setups-screen.tsx) so the dark panel counts
 * what the two lists show.
 */
export default function SetupsPage() {
  return <SetupsScreen />;
}
