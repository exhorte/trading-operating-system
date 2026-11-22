import type { LucideIcon } from "lucide-react";
import { BookOpen, FlaskConical, LayoutDashboard, MonitorCog, Settings, ShieldCheck, Wallet } from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  section: "operate" | "analyze" | "system";
  /** The one question the screen answers — its subtitle (information_architecture.md: one screen, one question). */
  question: string;
}

/**
 * Six screens for a system that trades by itself once launched (ADR 0043, 2026-11-14 — Musk's algorithm: question every screen, delete).
 *
 * Deleted that day, each because a screen that stays here already answers its question, or because an autonomous system does not need it:
 *
 *   /positions       — the Command Center lists what is open, with the same table and the « close all » button
 *   /preflight       — the session verdict repeated the readiness the System screen and « why no trade » give
 *   /market-context  — a reading of the market for a trader deciding by hand; the strategy reads the market itself
 *   /analyse         — breakdowns of the journal; the journal keeps the results
 *   /demarrage       — moved into System (start-up, conditions, the automatic gesture)
 *   /agents          — moved into System (the commands the system sent); the machine health is the terminals' readiness there
 *
 * Settings is pinned at the bottom of the sidebar (SETTINGS_ITEM), away from the screens one operates from.
 */
export const NAV_ITEMS: NavItem[] = [
  {
    label: "Command Center",
    href: "/",
    icon: LayoutDashboard,
    section: "operate",
    question: "Où en est le système, là, maintenant",
  },
  {
    label: "Risque",
    href: "/risk",
    icon: ShieldCheck,
    section: "operate",
    question: "Combien il reste avant le verrou",
  },
  {
    label: "Stratégie",
    href: "/setups",
    icon: FlaskConical,
    section: "analyze",
    question: "Ce que S01 voit et ce qu'elle a pris",
  },
  {
    label: "Journal",
    href: "/journal",
    icon: BookOpen,
    section: "analyze",
    question: "Ce que le système a pris, et ce que cela a donné",
  },
  {
    label: "Compte",
    href: "/account",
    icon: Wallet,
    section: "system",
    question: "Quel compte est branché, sous quelles règles",
  },
  {
    label: "Système",
    href: "/system",
    icon: MonitorCog,
    section: "system",
    question: "Le système peut-il trader, et sinon qu'est-ce qui bloque",
  },
];

export const SETTINGS_ITEM: NavItem = {
  label: "Réglages",
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
