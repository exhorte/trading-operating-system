"""Agreement between what the machine proposed and what was actually traded (S01 « Critère de réussite »; ADR 0011: agreement, never
performance) (port of ``lib/setup/reconciliation.ts``). Pure: plain sequences in, rows out — no database, no HTTP.

Not to be confused with ``domain/positions/reconciliation`` (the database's beliefs versus the broker's facts).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from trading_os.domain.primitives import DomainModel, Side
from trading_os.shared.time import to_epoch_ms


class AgreementClass(StrEnum):
    PROPOSED_AND_TAKEN = "PROPOSE_ET_PRIS"
    PROPOSED_AND_REFUSED = "PROPOSE_ET_REFUSE"
    TAKEN_WITHOUT_PROPOSAL = "PRIS_SANS_PROPOSITION"  # the class the S01 sheet calls the most important one


class AgreementProposal(DomainModel):
    symbol: str
    side: Side
    detected_at: datetime


class AgreementTrade(DomainModel):
    broker_position_id: str
    symbol: str
    side: Side
    opened_at: datetime


class AgreementRow(DomainModel):
    # (``class`` in the original; ``agreement`` here, ``class`` being a Python keyword — the golden test maps one onto the other)
    agreement: AgreementClass
    symbol: str
    side: Side
    proposal_detected_at: datetime | None
    trade_opened_at: datetime | None
    broker_position_id: str | None


def reconcile(
    proposals: Sequence[AgreementProposal], trades: Sequence[AgreementTrade], tolerance_minutes: float
) -> list[AgreementRow]:
    """Matches proposals to trades on the same symbol and side within ``tolerance_minutes`` of the proposal's detection time — « un
    trade pris trois minutes après une proposition sur le même niveau est le même trade ».

    Matching is GLOBALLY nearest-first (every valid pair is ranked by time distance and claimed in that order), not
    first-proposal-first: with two proposals a minute apart and one trade between them, the trade goes to whichever proposal it is
    actually closer to. Each trade matches at most one proposal, and vice versa. An unmatched proposal is ``PROPOSE_ET_REFUSE``; an
    unmatched trade is ``PRIS_SANS_PROPOSITION``."""
    tolerance_ms = tolerance_minutes * 60_000

    candidate_pairs: list[tuple[int, AgreementTrade, int]] = []
    for proposal_index, proposal in enumerate(proposals):
        detected_ms = to_epoch_ms(proposal.detected_at)
        for trade in trades:
            if trade.symbol != proposal.symbol or trade.side is not proposal.side:
                continue
            distance_ms = abs(to_epoch_ms(trade.opened_at) - detected_ms)
            if distance_ms <= tolerance_ms:
                candidate_pairs.append((proposal_index, trade, distance_ms))
    candidate_pairs.sort(key=lambda pair: pair[2])  # stable, like Array.prototype.sort

    match_by_proposal: dict[int, AgreementTrade] = {}
    matched_trades: set[str] = set()
    for proposal_index, trade, _ in candidate_pairs:
        if proposal_index in match_by_proposal or trade.broker_position_id in matched_trades:
            continue
        match_by_proposal[proposal_index] = trade
        matched_trades.add(trade.broker_position_id)

    rows: list[AgreementRow] = []
    for proposal_index, proposal in enumerate(proposals):
        match = match_by_proposal.get(proposal_index)
        rows.append(
            AgreementRow(
                agreement=AgreementClass.PROPOSED_AND_TAKEN, symbol=proposal.symbol, side=proposal.side,
                proposal_detected_at=proposal.detected_at, trade_opened_at=match.opened_at,
                broker_position_id=match.broker_position_id,
            )
            if match is not None
            else AgreementRow(
                agreement=AgreementClass.PROPOSED_AND_REFUSED, symbol=proposal.symbol, side=proposal.side,
                proposal_detected_at=proposal.detected_at, trade_opened_at=None, broker_position_id=None,
            )
        )  # fmt: skip

    for trade in trades:
        if trade.broker_position_id not in matched_trades:
            rows.append(
                AgreementRow(
                    agreement=AgreementClass.TAKEN_WITHOUT_PROPOSAL, symbol=trade.symbol, side=trade.side,
                    proposal_detected_at=None, trade_opened_at=trade.opened_at, broker_position_id=trade.broker_position_id,
                )
            )  # fmt: skip
    return rows
