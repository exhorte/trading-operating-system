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
  /** The one question the screen answers — its subtitle (information_architecture.md: one screen, one question). */
  question: string;
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
 * Settings is pinned at the bottom of the sidebar (SETTINGS_ITEM), away from
 * the screens one operates from.
 */
export const NAV_ITEMS: NavItem[] = [
  {
    label: "Command Center",
    href: "/",
    icon: LayoutDashboard,
    section: "operate",
    question: "Où j'en suis, là, maintenant",
  },
  {
    label: "Pré-vol",
    href: "/preflight",
    icon: ClipboardCheck,
    section: "operate",
    question: "Tout ce que le système vérifie lui-même avant la séance",
  },
  {
    label: "Market Context",
    href: "/market-context",
    icon: ChartCandlestick,
    section: "operate",
    question: "Pourquoi le marché est dans cet état",
  },
  {
    label: "Positions",
    href: "/positions",
    icon: Layers,
    section: "operate",
    question: "Ce qui est ouvert, et si cela correspond à ce que le système a envoyé",
  },
  {
    label: "Risque & Discipline",
    href: "/risk",
    icon: ShieldCheck,
    section: "operate",
    question: "Où en est ma discipline, et combien il me reste avant le verrou",
  },
  {
    label: "Trades Journal",
    href: "/journal",
    icon: BookOpen,
    section: "analyze",
    question: "Ce que j'ai pris, et dans quel cadre",
  },
  {
    label: "Analyse de compte",
    href: "/analyse",
    icon: ChartColumnBig,
    section: "analyze",
    question: "Ce que mes données disent de mon process",
  },
  {
    label: "Setups (S01)",
    href: "/setups",
    icon: FlaskConical,
    section: "analyze",
    question: "Ce que S01 a vu, et ce que j'ai pris",
  },
  {
    label: "Account",
    href: "/account",
    icon: Wallet,
    section: "system",
    question: "Quel compte est branché, sous quelles règles",
  },
  {
    label: "Agents & Audit",
    href: "/agents",
    icon: Cpu,
    section: "system",
    question: "Ce que le système a fait, et s'il est en vie",
  },
];

export const SETTINGS_ITEM: NavItem = {
  label: "Settings",
  href: "/settings",
  icon: Settings,
  section: "system",
  question: "Comment chaque compte est configuré et branché",
};

export const SECTION_LABELS: Record<NavItem["section"], string> = {
  operate: "Opérer",
  analyze: "Analyser",
  system: "Système",
};

export function isNavItemActive(pathname: string, item: NavItem): boolean {
  return item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
}

/** The screen a path belongs to — for the header's breadcrumb. */
export function navEntryFor(pathname: string): NavItem | null {
  return [...NAV_ITEMS, SETTINGS_ITEM].find((item) => isNavItemActive(pathname, item)) ?? null;
}

/** A screen by its route, for a page's own header (`<PageHeader screen={screenAt("/risk")} />`). */
export function screenAt(href: string): NavItem {
  const item = [...NAV_ITEMS, SETTINGS_ITEM].find((candidate) => candidate.href === href);
  if (!item) {
    throw new Error(`No screen registered at ${href}`);
  }
  return item;
}

export function pageTitleFor(pathname: string): string {
  return navEntryFor(pathname)?.label ?? "Trading OS";
}
