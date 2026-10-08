"use client";

import { useEffect } from "react";
import { useRefreshAccountSettings } from "@/lib/realtime/provider";
import { useAccountSettings } from "@/lib/accounts/use-account-settings";
import { CodeRulesCard } from "@/components/accounts/code-rules-card";
import { ConnectionProcedure } from "@/components/accounts/connection-procedure";
import { ExnessSettingsForm } from "@/components/accounts/exness-settings-form";
import { FtmoSettingsForm } from "@/components/accounts/ftmo-settings-form";
import { SettingsGuardBanner } from "@/components/accounts/settings-guard-banner";
import { SettingsHistory } from "@/components/accounts/settings-history";
import { SettingsMetrics } from "@/components/accounts/settings-metrics";
import { useSettingsSubmit } from "@/components/accounts/use-settings-submit";
import { PageHeader } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { SplitLayout } from "@/components/ui/split-layout";

/** The anti-tilt answer changes while the page is open — a trade, a lockout,
 *  MT5 closed — so the banner is re-read rather than trusted from load. */
const GUARD_REFRESH_MS = 30_000;

/**
 * Settings — « comment chaque compte est configuré et branché »
 * (T12 incrément 2).
 *
 * `/settings` was removed on 2026-09-20 for having nothing to set. It comes
 * back with what the trader actually has to configure: which FTMO challenge
 * is traded, the capital an Exness account is measured from, the text that
 * recognises each broker, and how each terminal gets attached.
 *
 * Every change goes to the backend's append-only ledger, which decides at the
 * moment of writing whether it applies now or at the next trading day
 * (AccountSettingsGuard): a limit never loosens mid-session (ADR 0007). The
 * rules themselves — FTMO's percentages, the trader's discipline limits —
 * are shown, not edited: they change by a commit. No credential is ever
 * asked for: MT5 logs in, the cockpit follows (ADR 0003).
 *
 * Composition (ADR 0017, « formulaire avec aperçu en direct »): the guard
 * answer and the two forms on the left, the dark panel of what is in force
 * (and when a change would apply) on the right and sticky; then the
 * connection procedure, the rules fixed in code, the history and the
 * « Important » note.
 */
export default function SettingsPage() {
  const { ledger, error, resolved } = useAccountSettings();
  const refresh = useRefreshAccountSettings();
  const ftmoSubmit = useSettingsSubmit();
  const exnessSubmit = useSettingsSubmit();
  const available = ledger !== null;

  useEffect(() => {
    const timer = setInterval(refresh, GUARD_REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        stickyAside
        main={
          <>
            <PageHeader screen={screenAt("/settings")} />
            <SettingsGuardBanner ledger={ledger} error={error} />
            {/* Keyed by the version the draft starts from: a save, a cancel or a
                change made in another tab resets the form to the new target. */}
            <FtmoSettingsForm
              key={`ftmo-${resolved.ftmo.pending?.versionId ?? resolved.ftmo.source?.versionId ?? "default"}`}
              resolution={resolved.ftmo}
              exness={resolved.settings.exness}
              available={available}
              submitState={ftmoSubmit.state}
              onSubmit={(settings) => void ftmoSubmit.submit({ firm: "ftmo", settings })}
            />
            <ExnessSettingsForm
              key={`exness-${resolved.exness.pending?.versionId ?? resolved.exness.source?.versionId ?? "default"}`}
              resolution={resolved.exness}
              ftmo={resolved.settings.ftmo}
              available={available}
              submitState={exnessSubmit.state}
              onSubmit={(settings) => void exnessSubmit.submit({ firm: "exness", settings })}
            />
          </>
        }
        aside={<SettingsMetrics ledger={ledger} error={error} resolved={resolved} />}
      />

      <ConnectionProcedure />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <CodeRulesCard ftmoPhase={resolved.settings.ftmo.challenge.phase} />
        <SettingsHistory versions={ledger?.versions ?? []} resolved={resolved} />
      </div>

      <Callout title="Important">
        Rien ici ne se connecte à un broker ni ne demande un identifiant : MT5 se connecte, le cockpit suit (ADR
        0003). Chaque changement est inscrit dans un registre en ajout seul, et le backend décide au moment
        d&apos;enregistrer s&apos;il s&apos;applique tout de suite ou au prochain jour de trading — une limite ne se
        desserre jamais en pleine séance (ADR 0007). Les pourcentages, eux, ne se changent que par un commit.
      </Callout>
    </div>
  );
}
