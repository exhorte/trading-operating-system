"use client";

import { useState } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { useRules } from "@/lib/accounts/use-rules";
import { PROVIDER_NAMES } from "@/lib/accounts/profile";
import { ConnectionHelp } from "@/components/accounts/connection-help";
import { ConnectAccountForm } from "@/components/accounts/connect-account-form";
import { Field, inputClass } from "@/components/accounts/form-controls";
import { RegisterAccountForm } from "@/components/accounts/register-account-form";
import { RulesForm, type SavedNotice } from "@/components/accounts/rules-form";
import { SettingsGuardBanner } from "@/components/accounts/settings-guard-banner";
import { SettingsHistory } from "@/components/accounts/settings-history";
import { SettingsMetrics } from "@/components/accounts/settings-metrics";
import { PageHeader } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { SplitLayout } from "@/components/ui/split-layout";

/**
 * Settings — « comment chaque compte est configuré et branché »
 * (T12 incrément 2).
 *
 * Which accounts exist, and the limits each one is held to. Every change to the
 * limits goes to the core's append-only ledger, which decides at the moment
 * of writing whether it applies now or at the next trading day (the anti-tilt
 * guard): a limit never loosens mid-session (ADR 0007). A password is asked only
 * by the connection form, goes to the core and is kept nowhere (ADR 0013, 0020).
 *
 * Composition (ADR 0017, « formulaire avec aperçu en direct »): the guard
 * answer, the account to set and its limits on the left, the dark panel of what
 * is in force (and when a change would apply) on the right and sticky; then the
 * connection of a new account from its broker identifiers, the registration
 * without connecting, the connection procedure, the history and the
 * « Important » note.
 */
export default function SettingsPage() {
  const { accounts, activeAccountId } = useCockpit();
  const [chosen, setChosen] = useState<string | null>(null);
  // The core's answer to the last save lives here: the form below is replaced by the very save that produces it.
  const [notice, setNotice] = useState<SavedNotice | null>(null);

  // The account being set: the one the trader picked, else the active one, else the first registered (an account archived
  // meanwhile simply stops being found, and the next one takes its place).
  const selected =
    accounts.find((a) => a.id === chosen) ?? accounts.find((a) => a.id === activeAccountId) ?? accounts[0] ?? null;
  const { data: overview, error, refresh } = useRules(selected?.id ?? null);

  // `RulesForm` is keyed by the version it starts from: a save, a withdrawal or a change made elsewhere resets it to the new target.
  const formKey = `${selected?.id ?? "none"}-${overview?.resolution.pending?.versionId ?? overview?.resolution.source?.versionId ?? "registered"}`;

  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        stickyAside
        main={
          <>
            <PageHeader screen={screenAt("/settings")} />
            <SettingsGuardBanner overview={overview} error={error} />
            {accounts.length > 1 && (
              <Field label="Compte à régler">
                <select
                  value={selected?.id ?? ""}
                  onChange={(e) => setChosen(e.target.value)}
                  className={inputClass}
                  aria-label="Compte à régler"
                >
                  {accounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {PROVIDER_NAMES[account.provider]} · {account.name} ({account.login})
                      {account.id === activeAccountId ? " — actif" : ""}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            {selected && overview ? (
              <RulesForm
                key={formKey}
                account={selected}
                overview={overview}
                onChanged={refresh}
                notice={notice}
                onNotice={setNotice}
              />
            ) : (
              !selected && (
                <Callout title="Aucun compte enregistré" variant="info">
                  Les limites sont celles d&apos;un compte : enregistre le premier ci-dessous, puis reviens ici les écrire.
                </Callout>
              )
            )}
          </>
        }
        aside={<SettingsMetrics account={selected} overview={overview} error={error} />}
      />

      <ConnectAccountForm />

      <RegisterAccountForm />

      <ConnectionHelp />

      {selected && overview && <SettingsHistory versions={overview.versions} registeredRules={selected} />}

      <Callout title="Important">
        Le seul formulaire qui touche un mot de passe est « Connecter un compte » : il va du champ au cœur, qui s&apos;en sert
        une fois pour lire le compte chez le courtier et ne le garde ni ne le journalise (ADR 0013, 0020) ; MT5 conserve le sien
        selon ses propres réglages. Chaque changement est inscrit dans un registre en ajout seul, et le cœur décide au moment d&apos;enregistrer s&apos;il
        s&apos;applique tout de suite ou au prochain jour de trading — une limite ne se desserre jamais en pleine séance (ADR
        0007). Le plafond d&apos;autonomie d&apos;un compte et ses fenêtres de trading ne se changent pas depuis cet écran.
      </Callout>
    </div>
  );
}
