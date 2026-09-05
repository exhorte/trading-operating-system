"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useCockpit, usePublishTicket } from "@/lib/realtime/provider";
import { useTradeDraft } from "./trade-draft-context";
import { Card } from "@/components/ui/card";
import { StatusPill } from "@/components/ui/status-pill";
import type { Confidence, PreTradeTicket, SetupType, TradeBias } from "@/lib/domain/ticket";

const SETUP_OPTIONS: { value: SetupType; label: string }[] = [
  { value: "fvg", label: "FVG" },
  { value: "order_block", label: "Order block" },
  { value: "liquidity_sweep", label: "Liquidity sweep" },
  { value: "retest", label: "Retest" },
  { value: "other", label: "Autre" },
];

const BIAS_OPTIONS: { value: TradeBias; label: string }[] = [
  { value: "long", label: "Long" },
  { value: "short", label: "Short" },
  { value: "contre_tendance", label: "Contre-tendance" },
];

const CONFIDENCE_OPTIONS: Confidence[] = [1, 2, 3, 4, 5];

/** Generous vs. a mock echo (near-instant) or a real hub round-trip. */
const CONFIRM_TIMEOUT_MS = 8_000;

function makeTicketId(): string {
  return `ticket-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function parseInput(value: string): number | null {
  if (value.trim() === "") {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function ChoiceButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded border px-2 py-1 text-xs ${
        active
          ? "border-accent bg-accent/15 text-foreground"
          : "border-border bg-surface-elevated text-muted hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

/**
 * T04 — pre-trade ticket. Four button-groups, no free text, prefilled from
 * T01's shared trade draft so nothing already on screen is retyped.
 *
 * A ticket is only ever considered stored once it echoes back through the
 * event stream with its own ticketId (lib/realtime/store.ts) — never on
 * submission alone. `confirmed` below is a pure derived value (pendingId +
 * the confirmed-ids list from the store), not local state kept in sync via
 * an effect: an effect that resets several pieces of state the moment an
 * external value changes is exactly the "setState-in-effect" anti-pattern,
 * and here it would also hide a subtler bug — a stale timer closure racing
 * the reset. Rendering an explicit "Nouveau ticket" step instead means the
 * trader sees confirmation happen, rather than the form silently clearing.
 */
export function TicketPanel() {
  const { account, confirmedTicketIds } = useCockpit();
  const publishTicket = usePublishTicket();
  const { draft } = useTradeDraft();

  const [setup, setSetup] = useState<SetupType | null>(null);
  const [bias, setBias] = useState<TradeBias | null>(null);
  const [confidence, setConfidence] = useState<Confidence | null>(null);
  const [invalidationOverride, setInvalidationOverride] = useState<string | null>(null);
  const [pendingTicketId, setPendingTicketId] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Timeout callbacks fire on their own schedule and would otherwise close
  // over a stale confirmedTicketIds from submission time — this ref is
  // side-effect-only (no setState), so it stays outside the lint rule.
  const confirmedIdsRef = useRef<string[]>(confirmedTicketIds);
  useEffect(() => {
    confirmedIdsRef.current = confirmedTicketIds;
  }, [confirmedTicketIds]);

  useEffect(
    () => () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    },
    [],
  );

  const invalidation = invalidationOverride ?? (draft.stopLoss !== null ? String(draft.stopLoss) : "");
  const confirmed = pendingTicketId !== null && confirmedTicketIds.includes(pendingTicketId);
  const pending = pendingTicketId !== null && !confirmed;

  const canSave =
    pendingTicketId === null &&
    account !== null &&
    setup !== null &&
    bias !== null &&
    confidence !== null &&
    draft.entryPrice !== null &&
    draft.stopLoss !== null;

  function handleSave() {
    if (!canSave || !account || !setup || !bias || confidence === null) {
      return;
    }
    const entryPrice = draft.entryPrice!;
    const stopLoss = draft.stopLoss!;
    const ticketId = makeTicketId();
    const ticket: PreTradeTicket = {
      ticketId,
      accountId: account.accountId,
      symbol: "XAUUSD",
      setup,
      bias,
      entryPrice,
      stopLoss,
      invalidation: parseInput(invalidation) ?? stopLoss,
      confidence,
      takeProfit: draft.takeProfit,
      targetVolume: draft.sizing?.decision?.approvedVolume ?? null,
      targetRiskUsd: draft.sizing?.targetRiskUsd ?? null,
      createdAt: new Date().toISOString(),
    };

    setFailed(false);
    setPendingTicketId(ticketId);
    timeoutRef.current = setTimeout(() => {
      if (!confirmedIdsRef.current.includes(ticketId)) {
        setPendingTicketId(null);
        setFailed(true);
      }
    }, CONFIRM_TIMEOUT_MS);
    publishTicket(ticket);
  }

  function handleNewTicket() {
    setPendingTicketId(null);
    setFailed(false);
    setSetup(null);
    setBias(null);
    setConfidence(null);
    setInvalidationOverride(null);
  }

  if (confirmed) {
    return (
      <Card title="Ticket pré-trade">
        <div className="flex flex-col gap-3">
          <StatusPill tone="profit">Ticket enregistré</StatusPill>
          <button
            type="button"
            onClick={handleNewTicket}
            className="rounded border border-border bg-surface-elevated px-2 py-1.5 text-xs text-foreground hover:border-accent"
          >
            Nouveau ticket
          </button>
        </div>
      </Card>
    );
  }

  return (
    <Card title="Ticket pré-trade">
      <div className="flex flex-col gap-3">
        {(draft.entryPrice === null || draft.stopLoss === null) && (
          <p className="text-xs text-muted">
            Renseigne d&rsquo;abord une entrée et un stop dans le panneau de sizing.
          </p>
        )}

        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted">Setup</span>
          <div className="flex flex-wrap gap-1">
            {SETUP_OPTIONS.map((opt) => (
              <ChoiceButton key={opt.value} active={setup === opt.value} onClick={() => setSetup(opt.value)}>
                {opt.label}
              </ChoiceButton>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted">Biais</span>
          <div className="flex flex-wrap gap-1">
            {BIAS_OPTIONS.map((opt) => (
              <ChoiceButton key={opt.value} active={bias === opt.value} onClick={() => setBias(opt.value)}>
                {opt.label}
              </ChoiceButton>
            ))}
          </div>
        </div>

        <label className="flex flex-col gap-1 text-xs text-muted">
          Invalidation
          <input
            type="number"
            inputMode="decimal"
            step="0.01"
            value={invalidation}
            onChange={(e) => setInvalidationOverride(e.target.value)}
            className="tnum rounded border border-border bg-surface-elevated px-2 py-1 text-sm text-foreground outline-none focus:border-accent"
          />
        </label>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted">Confiance</span>
          <div className="flex gap-1">
            {CONFIDENCE_OPTIONS.map((level) => (
              <ChoiceButton key={level} active={confidence === level} onClick={() => setConfidence(level)}>
                {level}
              </ChoiceButton>
            ))}
          </div>
        </div>

        <button
          type="button"
          disabled={!canSave}
          onClick={handleSave}
          className="rounded border border-accent bg-accent/15 px-2 py-1.5 text-xs font-medium text-foreground disabled:cursor-not-allowed disabled:border-border disabled:bg-surface-elevated disabled:text-muted"
        >
          {pending ? "Enregistrement…" : "Enregistrer le ticket"}
        </button>

        {pending && (
          <StatusPill tone="info" pulse>
            En cours — pas encore confirmé
          </StatusPill>
        )}
        {failed && (
          <p className="rounded border border-loss/40 bg-loss/10 px-2 py-1 text-xs text-loss">
            Non confirmé après {CONFIRM_TIMEOUT_MS / 1000}s — le ticket n&rsquo;est probablement pas
            enregistré. Réessaie.
          </p>
        )}
      </div>
    </Card>
  );
}
