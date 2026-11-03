"""N8 « Drawdown Flatlining » as a cap on the risk of the next trade (ADR 0031). **It can lower the risk, never raise it.**

What N8 says, in the notes (``07_trading_strategy``, N8 §j and §l), and is built here — each only ever reduces:

* **after a loss** — « dès une seule perte, retour immédiat à la plus petite unité, maintenue tant qu'un trade gagnant n'est pas validé »;
* **Win Set Cycle** — « après 5 gains consécutifs, le 6ᵉ trade est à l'unité minimale […] le compteur repart à zéro »;
* **under the starting capital** — « capital sous le capital de départ → minimum ».

What N8 says and is **not** built, because building it would be a decision the notes do not take (the user's rule of 2026-11-01: do not
invent what the sources leave open):

* the value of « la plus petite unité » — « dépend du confort » — so it is **a setting nobody has written yet**: until it is, N8 does nothing
  and says so (``unconfigured``);
* the step *up* (« gain avec solde supérieur au dépôt initial → un palier de plus »): it would raise a risk, and the size of a step is not
  given. The ceiling stays the grid of ADR 0019 — N8 never lifts it;
* the Soft Start (« jamais de risque maximal au démarrage d'une session »): what a « session » is, is not defined.

The granularity of every N8 value is **0.1 %** (the user's decision of 2026-11-01). The smallest unit is *not* a required minimum risk: it can be
0 — which blocks the next trade. The result is one more entry in the Risk Engine's list of caps; the final risk is the smallest of them all, so
N8 cannot go round the daily, weekly or total limits, the grid, or the broker's.

Pure: the same history gives the same cap.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from trading_os.domain.primitives import DomainModel

N8_UNIT_PERCENT = 0.1  # the granularity of N8's adjustments (ADR 0031)
N8_UNITS_PER_PERCENT = 10  # 1 % = 10 units; integers, so that 3 units is exactly 0.3 % and never 0.30000000000000004

N8State = Literal["off", "unconfigured", "free", "restricted"]


def units_to_percent(units: int) -> float:
    return units / N8_UNITS_PER_PERCENT


def percent_to_units(percent: float) -> int:
    """Whole 0.1 % units, or ``ValueError`` — a value between two units is refused, never rounded to one."""
    units = round(percent * N8_UNITS_PER_PERCENT)
    if abs(percent * N8_UNITS_PER_PERCENT - units) > 1e-6 or units < 0:
        raise ValueError(f"{percent!r} is not a whole number of {N8_UNIT_PERCENT} % units (0, 0.1, 0.2 …)")
    return units


class N8Policy(DomainModel):
    """The settings. Off by default, and inert until ``minimum_units`` is written: the notes do not say how large the smallest unit is."""

    enabled: bool = False
    # The smallest unit, in 0.1 % steps. 0 = block the next trade; 3 = cap it at 0.3 %. ``None`` = not written yet → N8 cannot act.
    minimum_units: int | None = Field(default=None, ge=0)
    reduce_after_loss: bool = True  # N8 §j.3
    wins_before_minimum: int = Field(default=5, ge=0)  # N8 §j.4, « Win Set Cycle »; 0 = this trigger off
    reduce_below_starting_equity: bool = True  # N8 §j.2 and §l.3

    @classmethod
    def from_percent(
        cls,
        *,
        enabled: bool,
        minimum_percent: float | None,
        reduce_after_loss: bool = True,
        wins_before_minimum: int = 5,
        reduce_below_starting_equity: bool = True,
    ) -> N8Policy:
        return cls(
            enabled=enabled,
            minimum_units=None if minimum_percent is None else percent_to_units(minimum_percent),
            reduce_after_loss=reduce_after_loss,
            wins_before_minimum=wins_before_minimum,
            reduce_below_starting_equity=reduce_below_starting_equity,
        )

    @property
    def active(self) -> bool:
        return self.enabled and self.minimum_units is not None

    @property
    def minimum_percent(self) -> float | None:
        return None if self.minimum_units is None else units_to_percent(self.minimum_units)


class N8Cap(DomainModel):
    """N8's answer for the next trade: which state it is in and, when restricted, the cap in percent and why."""

    state: N8State
    cap_percent: float | None = None
    triggers: tuple[str, ...] = ()
    detail: str


def _trigger_after_win_cycle(pnl_oldest_first: Sequence[float], wins_needed: int) -> bool:
    """True when the next trade is the one after a complete cycle of ``wins_needed`` wins in a row. The trade taken at the minimum ends
    the cycle whatever its result (« le compteur repart à zéro »). A trade that made nothing (0) is neither a win nor a loss."""
    wins = 0
    for pnl in pnl_oldest_first:
        if pnl == 0:
            continue
        if wins >= wins_needed:
            wins = 0  # that was the trade at the minimum: a new cycle starts
        elif pnl > 0:
            wins += 1
        else:
            wins = 0
    return wins >= wins_needed


def _last_decisive_was_a_loss(pnl_oldest_first: Sequence[float]) -> bool:
    for pnl in reversed(pnl_oldest_first):
        if pnl != 0:
            return pnl < 0
    return False


def evaluate_n8(
    policy: N8Policy,
    *,
    pnl_oldest_first: Sequence[float],
    history_known: bool,
    equity: float | None,
    starting_capital: float | None,
) -> N8Cap:
    """The cap N8 puts on the next trade. ``pnl_oldest_first`` is the realised result of the most recent closed trades (a bounded window —
    the cycle is counted inside it); ``history_known`` is False when the database could not be read, in which case nothing can be said about
    the last trade and, if N8 is active, the minimum applies (never an assumption in the direction of more risk)."""
    if not policy.enabled:
        return N8Cap(state="off", detail="N8 is off")
    if policy.minimum_units is None:
        return N8Cap(
            state="unconfigured",
            detail="N8 is on but its smallest unit is not written (the notes do not give it): it does nothing until it is",
        )
    triggers: list[str] = []
    if not history_known:
        triggers.append("history_unknown")
    else:
        if policy.reduce_after_loss and _last_decisive_was_a_loss(pnl_oldest_first):
            triggers.append("after_loss")
        if policy.wins_before_minimum > 0 and _trigger_after_win_cycle(pnl_oldest_first, policy.wins_before_minimum):
            triggers.append("win_set_cycle")
    if (
        policy.reduce_below_starting_equity
        and starting_capital is not None
        and equity is not None
        and starting_capital > 0
        and equity < starting_capital
    ):
        triggers.append("below_starting_equity")
    if not triggers:
        return N8Cap(state="free", detail="N8: no trigger — the grid decides")
    cap = units_to_percent(policy.minimum_units)
    text = {
        "after_loss": "the last trade lost: the smallest unit until one wins",
        "win_set_cycle": f"{policy.wins_before_minimum} wins in a row: the next trade at the smallest unit",
        "below_starting_equity": "equity is under the starting capital",
        "history_unknown": "the trade history could not be read",
    }
    return N8Cap(
        state="restricted",
        cap_percent=cap,
        triggers=tuple(triggers),
        detail=f"N8 caps the risk at {cap:g} % — " + "; ".join(text[t] for t in triggers),
    )


__all__ = [
    "N8_UNITS_PER_PERCENT",
    "N8_UNIT_PERCENT",
    "N8Cap",
    "N8Policy",
    "evaluate_n8",
    "percent_to_units",
    "units_to_percent",
]
