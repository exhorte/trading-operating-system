"use client";

import Link from "next/link";
import { useCockpit } from "@/lib/realtime/provider";
import { resolveActiveProfile } from "@/lib/accounts/active-profile";
import { detectFirm, FIRMS } from "@/lib/accounts/firm";
import { brokerMatchersOf } from "@/lib/accounts/settings";
import { useAccountSettings } from "@/lib/accounts/use-account-settings";
import { Panel } from "@/components/ui/panel";
import { ConnectionChain } from "@/components/accounts/connection-chain";
import { FirmAccountCard } from "@/components/accounts/firm-account-card";
import { ObjectivesCard } from "@/components/accounts/objectives-card";
import { RulesCard } from "@/components/accounts/rules-card";

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
 */
export default function AccountPage() {
  const { account } = useCockpit();
  const { resolved, error, ledger } = useAccountSettings();

  const connectedFirm = account ? detectFirm(account.broker, brokerMatchersOf(resolved.settings)) : null;
  const profile = account ? resolveActiveProfile(account, resolved.settings) : null;

  return (
    <div className="flex flex-col gap-5">
      {error && (
        <p className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
          Paramètres de compte non lus : {error}{" "}
          {ledger
            ? "— la dernière configuration lue reste appliquée."
            : "— les valeurs par défaut du code s'appliquent."}
        </p>
      )}

      <ConnectionChain profile={profile} />

      <div className="grid gap-5 lg:grid-cols-2">
        {FIRMS.map((firm) => (
          <FirmAccountCard key={firm} firm={firm} resolved={resolved} connectedFirm={connectedFirm} />
        ))}
      </div>

      {account && !profile && (
        <Panel title="Broker non reconnu">
          <p className="text-xs leading-relaxed text-foreground">
            Le terminal connecté se présente comme « {account.broker} » : ni «{" "}
            {resolved.settings.ftmo.brokerMatch} » ni « {resolved.settings.exness.brokerMatch} » n&apos;y
            figurent. Les règles par défaut s&apos;appliquent, et la perte max est mesurée depuis le solde
            au moment où le cockpit s&apos;est connecté — pas depuis une référence fixe.
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Si c&apos;est ton compte FTMO ou Exness, corrige son texte de reconnaissance dans{" "}
            <Link href="/settings" className="text-primary hover:underline">
              Settings
            </Link>
            .
          </p>
        </Panel>
      )}

      {profile && (
        <div className="grid gap-5 lg:grid-cols-2">
          <RulesCard profile={profile} />
          {profile.challenge ? (
            <ObjectivesCard profile={profile} />
          ) : (
            <Panel title="Objectifs">
              <p className="text-xs text-muted-foreground">
                Un compte en direct n&apos;a pas d&apos;objectifs imposés : ni objectif de profit ni
                nombre de jours minimum. Seules les limites de gauche s&apos;appliquent — et
                personne d&apos;autre que toi ne les fait respecter.
              </p>
            </Panel>
          )}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Le cockpit ne se connecte à aucun broker : il suit le terminal MT5 ouvert, et aucun
        identifiant n&apos;est demandé ni stocké. Le challenge, le capital de référence et la
        reconnaissance se changent dans{" "}
        <Link href="/settings" className="text-primary hover:underline">
          Settings
        </Link>{" "}
        ; les pourcentages dans <code className="text-foreground">lib/accounts/</code>, par un commit.
      </p>
    </div>
  );
}
