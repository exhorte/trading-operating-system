"use client";

import Link from "next/link";
import { useCockpit } from "@/lib/realtime/provider";
import { useActiveProfile } from "@/lib/accounts/use-rules";
import { AccountMetrics } from "@/components/accounts/account-metrics";
import { ConnectAccountForm } from "@/components/accounts/connect-account-form";
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
 * the trader connect an account from its broker identifiers, attach or detach.
 * **One account is connected at a time** (ADR 0021). A password, if given, is
 * used once by the core and kept nowhere (ADR 0013, 0020). Rules are edited in `/settings`.
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

      <div id="connecter" className="scroll-mt-24">
        <ConnectAccountForm />
      </div>

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
                ? "Le cœur ne connaît encore aucun compte. Connecte le tien avec le formulaire ci-dessus : Exness ou FTMO, le login, le serveur."
                : "Le cœur ne répond pas : la liste de tes comptes vient de lui."
            }
            hint="Le mot de passe, s'il est demandé, sert une fois à lire le compte et n'est gardé nulle part."
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
        Un seul compte est connecté à la fois. Le formulaire de connexion lit le compte chez le courtier avec ses identifiants ;
        le mot de passe, facultatif quand MT5 est déjà sur ce compte, sert une fois et n&apos;est ni stocké ni journalisé (ADR 0013,
        0020, 0021). Les limites et le capital de référence de chaque compte se règlent dans{" "}
        <Link href="/settings" className={LINK}>
          Settings
        </Link>
        , sous la règle anti-tilt : une limite ne se desserre jamais en pleine séance. Le plafond d&apos;autonomie d&apos;un
        compte ne se relève pas depuis cet écran.
      </Callout>
    </div>
  );
}
