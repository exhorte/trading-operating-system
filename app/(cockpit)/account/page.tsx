"use client";

import Link from "next/link";
import { useCockpit } from "@/lib/realtime/provider";
import { resolveActiveProfile } from "@/lib/accounts/active-profile";
import { detectFirm, FIRMS } from "@/lib/accounts/firm";
import { brokerMatchersOf } from "@/lib/accounts/settings";
import { useAccountSettings } from "@/lib/accounts/use-account-settings";
import { AccountMetrics } from "@/components/accounts/account-metrics";
import { ConnectionChain } from "@/components/accounts/connection-chain";
import { FirmAccountCard } from "@/components/accounts/firm-account-card";
import { ObjectivesCard } from "@/components/accounts/objectives-card";
import { RulesCard } from "@/components/accounts/rules-card";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { Panel } from "@/components/ui/panel";
import { SplitLayout } from "@/components/ui/split-layout";

const LINK = "text-foreground underline underline-offset-4 hover:no-underline";

/**
 * Account — « quel compte est branché, sous quelles règles, et comment
 * brancher l'autre » (T12 incrément 2, successor of `/comptes`).
 *
 * The two accounts this trader runs — an FTMO challenge and a direct Exness
 * account — side by side, whichever MT5 has open. Nothing here connects to a
 * broker: the observer attaches to the terminal the trader logged into, and
 * this screen reports each link of that chain, the firm the broker name was
 * recognised as, and the settings in effect for it. Settings are edited in
 * `/settings`; the percentages in `lib/accounts/`, by a commit.
 *
 * Composition (ADR 0017): the chain of links on the left, the connected
 * account's figures in the dark panel on the right, then the two configured
 * accounts, the rules and the objectives.
 */
export default function AccountPage() {
  const { account } = useCockpit();
  const { resolved, error, ledger } = useAccountSettings();

  const connectedFirm = account ? detectFirm(account.broker, brokerMatchersOf(resolved.settings)) : null;
  const profile = account ? resolveActiveProfile(account, resolved.settings) : null;

  return (
    <div className="flex flex-col gap-10">
      {error && (
        <Callout title="Paramètres de compte non lus" variant="warning">
          {error}{" "}
          {ledger
            ? "— la dernière configuration lue reste appliquée."
            : "— les valeurs par défaut du code s'appliquent."}
        </Callout>
      )}

      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/account")} />
            <ConnectionChain profile={profile} />
          </>
        }
        aside={<AccountMetrics profile={profile} />}
      />

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="Comptes configurés"
          subtitle="celui que MT5 a ouvert est marqué « Connecté »"
        />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {FIRMS.map((firm) => (
            <FirmAccountCard key={firm} firm={firm} resolved={resolved} connectedFirm={connectedFirm} />
          ))}
        </div>
      </section>

      {account && !profile && (
        <Callout title="Broker non reconnu" variant="warning">
          Le terminal connecté se présente comme « {account.broker} » : ni « {resolved.settings.ftmo.brokerMatch} » ni «{" "}
          {resolved.settings.exness.brokerMatch}{" "}
          » n&apos;y figurent. Les règles par défaut s&apos;appliquent, et la perte max est mesurée depuis le solde au
          moment où le cockpit s&apos;est connecté — pas depuis une référence fixe.
          Si c&apos;est ton compte FTMO ou Exness, corrige son texte de reconnaissance dans{" "}
          <Link href="/settings" className={LINK}>
            Settings
          </Link>
          .
        </Callout>
      )}

      {profile && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <RulesCard profile={profile} />
          {profile.challenge ? (
            <ObjectivesCard profile={profile} />
          ) : (
            <Panel title="Objectifs">
              <p className="text-sm text-muted-foreground">
                Un compte en direct n&apos;a pas d&apos;objectifs imposés : ni objectif de profit ni nombre de jours
                minimum. Seules les limites de gauche s&apos;appliquent — et personne d&apos;autre que toi ne les fait
                respecter.
              </p>
            </Panel>
          )}
        </div>
      )}

      <Callout title="Important">
        Le cockpit ne se connecte à aucun broker : il suit le terminal MT5 ouvert, et aucun identifiant n&apos;est
        demandé ni stocké. Le challenge, le capital de référence et la reconnaissance se changent dans{" "}
        <Link href="/settings" className={LINK}>
          Settings
        </Link>{" "}
        ; les pourcentages dans <code className="text-foreground">lib/accounts/</code>, par un commit.
      </Callout>
    </div>
  );
}
