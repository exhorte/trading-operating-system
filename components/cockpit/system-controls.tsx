"use client";

import { useApi } from "@/lib/api/use-api";
import { autopilotLine, MODE_LABELS, modeTone, verdictLine } from "@/lib/cockpit/startup";
import { CloseAllButton } from "@/components/cockpit/close-all-button";
import { StartSystemButton } from "@/components/cockpit/startup-panel";
import { StatusPill } from "@/components/ui/status-pill";

/**
 * The two gestures that make the system usable day to day, side by side and clearly apart: start it, and close what is open.
 * The mode is shown in the plan's words (OBSERVE … LIVE_AUTO) with what it allows, and a real account says so in red.
 * Closing never depends on the mode: it is offered in OFF, OBSERVE, CONFIRM and HALTED alike (ADR 0034). Below the verdict, the pilot
 * (ADR 0043): what it aims for, whether a person paused it, and the last thing it did.
 */
export function SystemControls() {
  const { data } = useApi("system_startup_status", {}, { pollMs: 3000 });
  const { data: pilot } = useApi("system_autopilot_status", {}, { pollMs: 5000 });
  return (
    <section aria-label="Contrôle du système" className="flex flex-col gap-3 rounded-xl border bg-card p-4 sm:p-5">
      {data?.realAccountBanner && (
        <p role="alert" className="rounded-lg bg-destructive px-4 py-2 text-sm font-semibold text-destructive-foreground">
          {data.realAccountBanner}
        </p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            {data ? (
              <StatusPill tone={modeTone(data.planMode)} pulse={data.planMode === "HALTED"}>
                {MODE_LABELS[data.planMode]}
              </StatusPill>
            ) : (
              <StatusPill tone="muted">Mode : lecture…</StatusPill>
            )}
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground">{data ? verdictLine(data) : "Lecture de l'état du système…"}</p>
          {pilot && pilot.target !== "OFF" && (
            <p className="mt-1 text-xs text-muted-foreground">
              {autopilotLine(pilot)}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StartSystemButton />
          <CloseAllButton />
        </div>
      </div>
    </section>
  );
}
