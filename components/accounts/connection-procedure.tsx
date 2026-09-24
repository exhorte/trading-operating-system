"use client";

import { useState } from "react";
import {
  AGENT_MAGIC_SUGGESTION,
  agentAllowedSymbols,
  observerCommand,
  START_LIVE_COMMAND,
  terminalSymbol,
} from "@/lib/accounts/connection";
import { FIRMS, type Firm } from "@/lib/accounts/firm";
import { Card } from "@/components/ui/card";
import { secondaryButtonClass } from "./form-controls";

const FIRM_NAMES: Record<Firm, string> = { ftmo: "FTMO", exness: "Exness" };

function CopyableCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-1 flex items-center gap-2">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded border border-border bg-surface-elevated px-2 py-1 text-[11px] text-foreground">
        {command}
      </code>
      <button
        type="button"
        className={secondaryButtonClass}
        onClick={() => {
          void navigator.clipboard?.writeText(command).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1_500);
          });
        }}
      >
        {copied ? "Copié" : "Copier"}
      </button>
    </div>
  );
}

function FirmProcedure({ firm }: { firm: Firm }) {
  const name = FIRM_NAMES[firm];
  return (
    <div>
      <h3 className="text-xs font-medium text-foreground">{name}</h3>
      <ol className="mt-2 flex list-decimal flex-col gap-2 pl-4 text-[11px] leading-snug text-muted">
        <li>
          Dans MT5 : <span className="text-foreground">Fichier → Connexion à un compte de trading</span>, et
          choisis le compte {name}. Le mot de passe reste dans MT5 — le Trading OS ne le demande jamais.
        </li>
        <li>
          Depuis <code className="text-foreground">04_code</code>, (re)lance l&apos;observer en lecture seule
          avec le symbole tel que ce terminal le nomme :
          <CopyableCommand command={observerCommand(firm)} />
        </li>
        <li>
          Facultatif — l&apos;agent EA-05 sur un graphique de ce terminal, avec ses paramètres saisis dans
          MT5 : <code className="text-foreground">InpAccountId</code> = le numéro du compte,{" "}
          <code className="text-foreground">InpMagicNumber</code> ={" "}
          <code className="text-foreground">{AGENT_MAGIC_SUGGESTION[firm]}</code> (suggestion — jamais le
          même que l&apos;autre compte),{" "}
          <code className="text-foreground">InpAllowedSymbolsCsv</code> ={" "}
          <code className="text-foreground">{agentAllowedSymbols(firm)}</code>.
        </li>
        <li>
          Sur <span className="text-foreground">Account</span>, la carte {name} passe à « Connecté » et la
          liaison montre le profil reconnu.
        </li>
      </ol>
    </div>
  );
}

/**
 * How to connect each account — the only way there is: MT5 logs in, the
 * observer attaches (ADR 0003). One account at a time (T12, décision 1):
 * switching accounts means switching in MT5 and restarting the observer, so
 * its hello carries the new broker and the right symbol.
 */
export function ConnectionProcedure() {
  return (
    <Card title="Connexion MT5 — procédure">
      <div className="mb-4 rounded border border-border bg-surface-elevated px-3 py-2 text-[11px] leading-snug text-muted">
        <p>
          En une commande, depuis <code className="text-foreground">04_code</code>, une fois MT5 ouvert et
          connecté au compte : base, backend, observer sur le bon symbole et cockpit démarrent dans
          l&apos;ordre, le compte ouvert est détecté (ajoute{" "}
          <code className="text-foreground">-WithSetupPipeline</code> pour le pipeline S01).
        </p>
        <CopyableCommand command={START_LIVE_COMMAND} />
      </div>
      <div id="connexion" className="grid gap-4 lg:grid-cols-2">
        {FIRMS.map((firm) => (
          <FirmProcedure key={firm} firm={firm} />
        ))}
      </div>
      <p className="mt-3 border-t border-border pt-3 text-[11px] leading-snug text-muted">
        Un compte à la fois : le cockpit suit le terminal auquel l&apos;observer est attaché. Pour
        passer de l&apos;un à l&apos;autre, change de compte dans MT5 puis relance l&apos;observer —
        son premier message transmet le nouveau broker, et le symbole n&apos;est pas le même
        (FTMO <code className="text-foreground">{terminalSymbol("ftmo", "XAUUSD")}</code>, Exness{" "}
        <code className="text-foreground">{terminalSymbol("exness", "XAUUSD")}</code> : lancé avec le
        mauvais, l&apos;observer s&apos;arrête sur « symbol not found »).
      </p>
    </Card>
  );
}
