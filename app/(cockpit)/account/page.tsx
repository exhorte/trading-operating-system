"use client";

import Link from "next/link";
import { useCockpit } from "@/lib/realtime/provider";
import { useActiveProfile } from "@/lib/accounts/use-rules";
import { AccountMetrics } from "@/components/accounts/account-metrics";
import { ConnectionChain } from "@/components/accounts/connection-chain";
import { ObjectivesCard } from "@/components/accounts/objectives-card";
import { RegisteredAccountCard } from "@/components/accounts/registered-account-card";
import { RulesCard } from "@/components/accounts/rules-card";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { EmptyState } from "@/components/ui/empty-state";
import { Panel } from "@/components/ui/panel";
import { SplitLayout } from "@/components/ui/split-layout";
import { Wallet } from "lucide-react";

const LINK = "text-foreground underline underline-offset-4 hover:no-underline";

/**
 * Account — « quel compte est branché, sous quelles règles, et comment
 * brancher l'autre » (T12 incrément 2, successor of `/comptes`).
 *
 * The accounts this trader runs — an FTMO challenge, a direct Exness account —
 * are registered in the core, each with its own rules. Exactly one is active: the
 * one the core is attached to and the only one that can receive automatic
 * commands. This screen reports each link of the chain from the cockpit to the
 * terminal, the active account's figures and the rules that govern it, and lets
 * the trader attach, detach or switch. Nothing here logs in to a broker:
 * the terminal is logged in by the trader and the core follows it (ADR 0013).
 * Rules are edited in `/settings`.
 *
 * Composition (ADR 0017): the chain of links on the left, the active account's
 * figures in the dark panel on the right, then the registered accounts, the rules
 * and the objectives.
 */
export default function AccountPage() {
  const { accounts, activeAccountId, connection } = useCockpit();
  const { profile, error } = useActiveProfile();

  return (
    <div className="flex flex-col gap-10">
      {error && (
        <Callout title="Règles du compte non lues" variant="warning">
          {error.message}
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
          title="Comptes enregistrés"
          subtitle="celui que le cœur a rattaché et rendu actif est marqué « Actif »"
        />
        {accounts.length === 0 ? (
          <EmptyState
            icon={Wallet}
            title={connection === "connected" ? "Aucun compte enregistré" : "Comptes illisibles"}
            description={
              connection === "connected"
                ? "Le cœur ne connaît encore aucun compte. Enregistre le tien dans Settings : un login, un serveur, le type de compte."
                : "Le cœur ne répond pas : la liste de tes comptes vient de lui."
            }
            hint="Aucun mot de passe n'est demandé : MT5 se connecte, le cœur suit."
          />
        ) : (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {accounts.map((account) => (
              <RegisteredAccountCard key={account.id} account={account} active={account.id === activeAccountId} />
            ))}
          </div>
        )}
      </section>

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
        Le Trading OS ne se connecte à aucun broker : il suit le terminal MT5 ouvert, et aucun mot de passe de compte n&apos;est
        demandé ni stocké. Les limites et le capital de référence de chaque compte se règlent dans{" "}
        <Link href="/settings" className={LINK}>
          Settings
        </Link>
        , sous la règle anti-tilt : une limite ne se desserre jamais en pleine séance. Le plafond d&apos;autonomie d&apos;un
        compte ne se relève pas depuis cet écran.
      </Callout>
    </div>
  );
}
