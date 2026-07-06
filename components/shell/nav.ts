export type IconName =
  | "grid"
  | "chart"
  | "signal"
  | "layers"
  | "book"
  | "replay"
  | "shield"
  | "cpu"
  | "flask"
  | "settings";

export interface NavItem {
  label: string;
  href: string;
  icon: IconName;
  section: "operate" | "analyze" | "system";
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Command Center", href: "/", icon: "grid", section: "operate" },
  { label: "Market Context", href: "/market-context", icon: "chart", section: "operate" },
  { label: "Signals", href: "/signals", icon: "signal", section: "operate" },
  { label: "Positions", href: "/positions", icon: "layers", section: "operate" },
  { label: "Risk Monitor", href: "/risk", icon: "shield", section: "operate" },
  { label: "Trades Journal", href: "/journal", icon: "book", section: "analyze" },
  { label: "Replay", href: "/replay", icon: "replay", section: "analyze" },
  { label: "Backtests", href: "/backtests", icon: "flask", section: "analyze" },
  { label: "Execution Agents", href: "/agents", icon: "cpu", section: "system" },
  { label: "Settings", href: "/settings", icon: "settings", section: "system" },
];

export const SECTION_LABELS: Record<NavItem["section"], string> = {
  operate: "Operate",
  analyze: "Analyze",
  system: "System",
};

export function pageTitleFor(pathname: string): string {
  const match = NAV_ITEMS.find((item) =>
    item.href === "/" ? pathname === "/" : pathname.startsWith(item.href),
  );
  return match?.label ?? "Trading OS";
}
