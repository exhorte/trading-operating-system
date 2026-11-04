"""The commission an account really pays, and where that number came from (ADR 0036).

A commission is a property of the **account**, not of a provider. Applying « about 5 $ a lot » to every account was a guess standing in for
a measurement — it was applied to the Exness Standard demo, which announces none. The order of trust is now:

1. **observed** — what the broker charged on the account's own closed positions (the ``commission`` of their deals, per lot, round trip);
2. **documentary** — what the product's contract states (Exness Standard: none), until the account's own deals say otherwise;
3. **assumed** — the figure the trader configured, for a product whose commission the contract does not state (FTMO publishes it per symbol
   on its site). It is labelled as an assumption wherever it is shown, and it is replaced the day the first round trip is observed.

A reading that contradicts the documentation (the broker charges what the contract says it does not) is flagged, not hidden.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import Field

from trading_os.domain.primitives import DomainModel
from trading_os.domain.providers.rules import ProviderRuleSet

MIN_ROUND_TRIPS = 1  # how many fully closed positions make an observation (one is a measurement; more only narrow it)
DOCUMENTARY_TOLERANCE = 0.005  # a lot-commission this close to the documented one is the documented one (rounding)


class CommissionSource(StrEnum):
    OBSERVED = "observed"
    DOCUMENTARY = "documentary"
    ASSUMED = "assumed"


class CommissionDeal(DomainModel):
    """The part of a deal that matters here. ``entry`` is MT5's: ``in`` opens or adds, ``out`` closes or reduces."""

    position_id: int
    entry: Literal["in", "out"]
    volume: float = Field(ge=0)
    commission: float  # the broker's charge, negative as MT5 reports it


class CommissionReading(DomainModel):
    per_lot_round_trip: float = Field(ge=0)  # account currency, as a cost (positive)
    source: CommissionSource
    detail: str
    round_trips: int = 0
    documentary_mismatch: bool = False


def observed_commission(deals: Sequence[CommissionDeal]) -> tuple[float, int] | None:
    """The per-lot round-trip commission over the positions that are **fully closed** in ``deals``, and how many they are; ``None`` when
    none is. A position still open, or only partly closed, is left out: its entry commission is paid but its lots are not all
    accounted, and counting it would understate the rate."""
    by_position: dict[int, list[CommissionDeal]] = {}
    for deal in deals:
        by_position.setdefault(deal.position_id, []).append(deal)
    cost = closed_volume = 0.0
    trips = 0
    for position in by_position.values():
        opened = sum(deal.volume for deal in position if deal.entry == "in")
        closed = sum(deal.volume for deal in position if deal.entry == "out")
        if opened <= 0 or abs(opened - closed) > 1e-9:
            continue
        cost += -sum(deal.commission for deal in position)
        closed_volume += closed
        trips += 1
    if trips < MIN_ROUND_TRIPS or closed_volume <= 0:
        return None
    return max(0.0, cost) / closed_volume, trips


def resolve_commission(
    *, deals: Sequence[CommissionDeal] | None, rule_set: ProviderRuleSet | None, configured: float
) -> CommissionReading:
    """Observed, else documentary, else the configured assumption. ``deals is None`` = the history could not be read: the observation is
    then absent, not zero."""
    documentary = rule_set.documentary_commission_per_lot if rule_set is not None else None
    observed = observed_commission(deals) if deals is not None else None
    if observed is not None:
        rate, trips = observed
        mismatch = documentary is not None and abs(rate - documentary) > DOCUMENTARY_TOLERANCE
        note = f"; the contract states {documentary:g}, the broker charged otherwise" if mismatch else ""
        return CommissionReading(
            per_lot_round_trip=round(rate, 4),
            source=CommissionSource.OBSERVED,
            detail=f"{rate:.2f} per lot round trip over {trips} closed position(s){note}",
            round_trips=trips,
            documentary_mismatch=mismatch,
        )
    if documentary is not None:
        return CommissionReading(
            per_lot_round_trip=documentary,
            source=CommissionSource.DOCUMENTARY,
            detail=f"{documentary:g} per lot: what the product's contract states, until the account's own deals say otherwise",
        )
    return CommissionReading(
        per_lot_round_trip=configured,
        source=CommissionSource.ASSUMED,
        detail=f"{configured:g} per lot: the figure configured, an assumption — no closed position yet shows what the broker charges",
    )


__all__ = [
    "CommissionDeal",
    "CommissionReading",
    "CommissionSource",
    "observed_commission",
    "resolve_commission",
]
