import { Plug } from "lucide-react";
import { Panel } from "@/components/ui/panel";

/**
 * How an account gets attached: MT5 is logged in (by the trader, or by the connection form
 * with a password the core uses once and keeps nowhere), the core attaches (ADR 0013, 0020). One terminal can follow one account at a time; the
 * accounts are switched from Account, and the core refuses to switch away from
 * an account that is holding risk.
 */
export function ConnectionHelp() {
  return (
    <Panel title="Connexion MT5 — procédure" description="MT5 se connecte, le cœur s'attache" icon={Plug}>
      <ol className="flex list-decimal flex-col gap-3 pl-4 text-sm leading-snug text-muted-foreground">
        <li>
          Le plus simple : <span className="text-foreground">Connecter un compte</span> depuis Account — le login, le serveur et,
          si MT5 n&apos;est pas déjà sur ce compte, son mot de passe. Le cœur s&apos;en sert une fois pour lire le compte
          chez le courtier ; il ne le garde, ne le journalise et ne le renvoie jamais. Sinon, dans MT5 :{" "}
          <span className="text-foreground">Fichier → Connexion à un compte de trading</span>, et choisis le compte.
        </li>
        <li>
          Ici, <span className="text-foreground">Enregistrer sans se connecter</span> (une seule fois par compte) : le
          login, le serveur, le type. Le cœur en tire les limites du fournisseur, que tu ajustes ensuite.
        </li>
        <li>
          Dans <span className="text-foreground">Account</span>, <span className="text-foreground">Rattacher</span> : le cœur
          lit le terminal, vérifie qu&apos;il est bien sur ce login (un autre login est refusé, jamais pris pour celui-là), et
          le rend actif s&apos;il n&apos;y en avait pas.
        </li>
        <li>
          Facultatif — l&apos;agent d&apos;exécution EA-05 sur un graphique de ce terminal, avec ses paramètres saisis dans MT5 :{" "}
          <code className="text-foreground">InpAccountId</code> = le numéro du compte,{" "}
          <code className="text-foreground">InpMagicNumber</code> = un nombre propre à ce compte (jamais le même que l&apos;autre).
        </li>
      </ol>
      <p className="mt-5 border-t pt-4 text-sm leading-snug text-muted-foreground">
        Un seul compte est connecté à la fois : pour en prendre un autre, détache le premier. Détacher est refusé tant qu&apos;une
        position, un ordre en attente ou une commande en doute pourrait être perdu de vue.
      </p>
    </Panel>
  );
}
