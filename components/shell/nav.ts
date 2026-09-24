import type { LucideIcon } from "lucide-react";
import {
  BookOpen,
  ChartCandlestick,
  ChartColumnBig,
  ClipboardCheck,
  Cpu,
  FlaskConical,
  Layers,
  LayoutDashboard,
  Settings,
  ShieldCheck,
  Wallet,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
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
 *
 * Since the 2026-09-24 redesign, Settings is pinned at the bottom of the
 * sidebar (SETTINGS_ITEM), away from the screens one operates from.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: "Command Center", href: "/", icon: LayoutDashboard, section: "operate" },
  { label: "Pré-vol", href: "/preflight", icon: ClipboardCheck, section: "operate" },
  { label: "Market Context", href: "/market-context", icon: ChartCandlestick, section: "operate" },
  { label: "Positions", href: "/positions", icon: Layers, section: "operate" },
  { label: "Risque & Discipline", href: "/risk", icon: ShieldCheck, section: "operate" },
  { label: "Trades Journal", href: "/journal", icon: BookOpen, section: "analyze" },
  { label: "Analyse de compte", href: "/analyse", icon: ChartColumnBig, section: "analyze" },
  { label: "Setups (S01)", href: "/setups", icon: FlaskConical, section: "analyze" },
  { label: "Account", href: "/account", icon: Wallet, section: "system" },
  { label: "Agents & Audit", href: "/agents", icon: Cpu, section: "system" },
];

export const SETTINGS_ITEM: NavItem = {
  label: "Settings",
  href: "/settings",
  icon: Settings,
  section: "system",
};

export const SECTION_LABELS: Record<NavItem["section"], string> = {
  operate: "Opérer",
  analyze: "Analyser",
  system: "Système",
};

export function isNavItemActive(pathname: string, item: NavItem): boolean {
  return item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
}

/** The screen a path belongs to — for the header's title and breadcrumb. */
export function navEntryFor(pathname: string): NavItem | null {
  return [...NAV_ITEMS, SETTINGS_ITEM].find((item) => isNavItemActive(pathname, item)) ?? null;
}

export function pageTitleFor(pathname: string): string {
  return navEntryFor(pathname)?.label ?? "Trading OS";
}
