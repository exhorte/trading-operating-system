export type IconName =
  | "grid"
  | "checklist"
  | "chart"
  | "layers"
  | "book"
  | "shield"
  | "report"
  | "cpu"
  | "wallet"
  | "gear"
  | "flask";

export interface NavItem {
  label: string;
  href: string;
  icon: IconName;
  section: "operate" | "analyze" | "system";
}

/**
 * Eleven screens, all of which carry something.
 *
 * Until 2026-09-20 there were ten and five of them were "not built yet"
 * placeholders — a navigation that advertises screens with nothing behind
 * them costs a click every time to learn that again. Three of the five were
 * filled from what the Command Center was carrying (market context, risk,
 * agents); the two with nothing to receive were removed:
 *
 *   /settings — no auth, no backend switch, no strategy parameter to set
 *   /replay   — needs the analytics pipeline (ADR 0011), not started
 *
 * Both come back when they have content. /settings did, in two steps:
 * /comptes (T12, 2026-09-21) showed the account profile read-only; since
 * T12 incrément 2 (2026-09-23) that became Account (what is connected, under
 * which rules) and Settings (the account settings ledger and the connection
 * procedure). See context/frontend/information_architecture.md.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: "Command Center", href: "/", icon: "grid", section: "operate" },
  { label: "Pré-vol", href: "/preflight", icon: "checklist", section: "operate" },
  { label: "Market Context", href: "/market-context", icon: "chart", section: "operate" },
  { label: "Positions", href: "/positions", icon: "layers", section: "operate" },
  { label: "Risque & Discipline", href: "/risk", icon: "shield", section: "operate" },
  { label: "Trades Journal", href: "/journal", icon: "book", section: "analyze" },
  { label: "Analyse de compte", href: "/analyse", icon: "report", section: "analyze" },
  { label: "Setups (S01)", href: "/setups", icon: "flask", section: "analyze" },
  { label: "Account", href: "/account", icon: "wallet", section: "system" },
  { label: "Settings", href: "/settings", icon: "gear", section: "system" },
  { label: "Agents & Audit", href: "/agents", icon: "cpu", section: "system" },
];

export const SECTION_LABELS: Record<NavItem["section"], string> = {
  operate: "Opérer",
  analyze: "Analyser",
  system: "Système",
};

export function pageTitleFor(pathname: string): string {
  const match = NAV_ITEMS.find((item) =>
    item.href === "/" ? pathname === "/" : pathname.startsWith(item.href),
  );
  return match?.label ?? "Trading OS";
}
