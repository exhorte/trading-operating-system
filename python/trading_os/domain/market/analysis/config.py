"""Tunable knobs of the analysis engine (port of ``lib/analysis/config.ts``).

Every value is a hypothesis, not a validated edge. Tolerances are raw price units: the defaults below are scaled for XAUUSD (a
price near 4000); an FX pair needs its own (S01 poses 3 pips and 1 pip — see ``domain/strategy/s01``).
"""

from __future__ import annotations

from pydantic import Field

from trading_os.domain.market.sessions import DEFAULT_SESSION_WINDOWS, SessionWindow
from trading_os.domain.primitives import DomainModel


class ScoreWeights(DomainModel):
    """Max points awarded per confluence component."""

    structure: float  # aligned market structure (BOS/CHOCH in the bias direction)
    liquidity_sweep: float  # a liquidity pool was recently swept
    pd_array: float  # price sits in an unmitigated FVG/OB in the bias direction
    session: float  # the current session is a configured trading window
    premium_discount: float  # price is in the right premium/discount half for the bias


class AnalysisConfig(DomainModel):
    swing_lookback: int = Field(ge=1)  # bars required on each side to confirm a swing
    equal_level_tolerance: float = Field(ge=0)  # max distance for two swings to count as equal highs/lows
    min_fvg_size: float = Field(gt=0)  # minimum gap for a three-candle imbalance to count
    structure_swing_window: int = Field(ge=1)  # how many recent swings feed structure/liquidity detection
    session_windows: tuple[SessionWindow, ...] = DEFAULT_SESSION_WINDOWS
    score_weights: ScoreWeights


DEFAULT_ANALYSIS_CONFIG = AnalysisConfig(
    swing_lookback=2,
    equal_level_tolerance=0.3,
    min_fvg_size=0.2,
    structure_swing_window=12,
    session_windows=DEFAULT_SESSION_WINDOWS,
    score_weights=ScoreWeights(structure=3, liquidity_sweep=2, pd_array=3, session=1, premium_discount=1),
)


def max_score_of(weights: ScoreWeights) -> float:
    """Sum of every component weight — the denominator of a context score (added in the TypeScript's order)."""
    return weights.structure + weights.liquidity_sweep + weights.pd_array + weights.session + weights.premium_discount
