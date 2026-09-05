import type { ReactNode } from "react";
import { CockpitShell } from "@/components/shell/cockpit-shell";

export default function CockpitLayout({ children }: { children: ReactNode }) {
  return <CockpitShell>{children}</CockpitShell>;
}
