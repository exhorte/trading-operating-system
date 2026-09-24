"use client";

import { useState } from "react";
import { useRefreshAccountSettings } from "@/lib/realtime/provider";
import { requestSettingsChange, type SettingsChange } from "@/lib/accounts/settings-api";
import { describeGuardReason, type SettingsVersion } from "@/lib/accounts/settings";

export type SubmitState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "saved"; version: SettingsVersion; message: string }
  | { status: "failed"; message: string };

/**
 * Send one settings change and report what the backend decided. The page
 * never guesses whether it applies now: the answer is the version the
 * backend wrote (AccountSettingsGuard ran at that instant).
 */
export function useSettingsSubmit() {
  const refresh = useRefreshAccountSettings();
  const [state, setState] = useState<SubmitState>({ status: "idle" });

  async function submit(change: SettingsChange): Promise<void> {
    setState({ status: "saving" });
    try {
      const version = await requestSettingsChange(change);
      setState({
        status: "saved",
        version,
        message: version.deferred
          ? `Enregistré — appliqué au prochain jour de trading : ${version.deferralReasons
              .map(describeGuardReason)
              .join(" ")}`
          : "Enregistré — appliqué immédiatement : aucune séance n'était en cours.",
      });
    } catch (error) {
      setState({
        status: "failed",
        message: error instanceof Error ? error.message : "Enregistrement impossible.",
      });
    } finally {
      refresh();
    }
  }

  return { state, submit };
}
