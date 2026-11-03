"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Wallet } from "lucide-react";
import { useCockpit } from "@/lib/realtime/provider";
import { showsConnectGate } from "@/lib/accounts/connected";
import { ConnectAccountForm } from "@/components/accounts/connect-account-form";
import { RegisteredAccountCard } from "@/components/accounts/registered-account-card";
import { SectionHeading } from "./page-header";

/**
 * What a screen shows when no account is connected (ADR 0021): the way to connect one, not grey placeholders.
 *
 * Every screen but Account and Settings reads an account's figures; with none connected they used to draw skeletons that never
 * filled, and the trader had no way to know why, or what to do. The core says when « no account » is a fact (its first snapshot
 * has arrived and none is connected); until then the screen's own loading state stands. Accounts already registered are listed
 * below the form, with their « Rattacher » button: after a restart that is the usual way back.
 */
export function ConnectGate({ children }: { children: ReactNode }) {
  const { accounts, connection, version } = useCockpit();
  const pathname = usePathname();

  if (!showsConnectGate({ connection, version, accounts }, pathname)) {
    return <>{children}</>;
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-[1.75rem]">Connecte un compte</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Aucun compte n&apos;est connecté : cet écran lit les chiffres d&apos;un compte, et il n&apos;y en a pas encore à lire. Un
          seul compte est connecté à la fois.
        </p>
      </div>

      <ConnectAccountForm />

      {accounts.length > 0 && (
        <section className="flex flex-col gap-4">
          <SectionHeading
            title="Comptes déjà enregistrés"
            subtitle="ouvre le compte dans MT5, puis rattache-le"
            icon={Wallet}
          />
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {accounts.map((account) => (
              <RegisteredAccountCard key={account.id} account={account} active={false} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
