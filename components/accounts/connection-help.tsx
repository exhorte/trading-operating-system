import { Plug } from "lucide-react";
import { Panel } from "@/components/ui/panel";

/**
 * How an account gets attached — the only way there is: MT5 logs in, the core
 * attaches (ADR 0003, 0013). One terminal can follow one account at a time; the
 * accounts are switched from Account, and the core refuses to switch away from
 * an account that is holding risk.
 */
export function ConnectionHelp() {
  return (
    <Panel title="Connexion MT5 — procédure" description="MT5 se connecte, le cœur s'attache" icon={Plug}>
      <ol className="flex list-decimal flex-col gap-3 pl-4 text-sm leading-snug text-muted-foreground">
        <li>
          Dans MT5 : <span className="text-foreground">Fichier → Connexion à un compte de trading</span>, et choisis le
          compte. Le mot de passe reste dans MT5 — le Trading OS ne le demande jamais, ne le stocke pas et ne le transmet
          pas.
        </li>
        <li>
          Ici, <span className="text-foreground">Enregistrer un compte</span> (une seule fois par compte) : le login, le
          serveur, le type. Le cœur en tire les limites du fournisseur, que tu ajustes ensuite.
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
        Un terminal, des comptes successifs : détacher ou changer de compte est refusé tant qu&apos;une position, un ordre en
        attente ou une commande en doute pourrait être perdu de vue. Deux comptes rattachés en même temps exigent deux terminaux
        (le chemin du <code className="text-foreground">terminal.exe</code> de chacun, à l&apos;enregistrement).
      </p>
    </Panel>
  );
}
