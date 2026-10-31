"""Confluence scoring: turn the detected features into a weighted, testable score with a per-component breakdown (port of
``lib/analysis/scoring.ts``). This is the « why » behind a context and a hypothesis only — the weights are not a validated edge."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from trading_os.domain.market.analysis.config import ScoreWeights
from trading_os.domain.market.analysis.models import AnalysisFeatures, FairValueGap, OrderBlock, ScoreComponent
from trading_os.domain.primitives import Bias
from trading_os.shared.numbers import js_round


@dataclass(frozen=True)
class ScoreResult:
    score: float
    max_score: float
    breakdown: list[ScoreComponent]


def _pd_array_score(
    bias: Bias, price: float, fvgs: Sequence[FairValueGap], order_blocks: Sequence[OrderBlock], weight: float
) -> float:
    """Award for an unmitigated PD array aligned with the bias: full if price is inside it, half if it merely exists."""
    if bias is Bias.NEUTRAL:
        return 0.0
    aligned: list[FairValueGap | OrderBlock] = [
        *(g for g in fvgs if g.direction is bias and g.mitigated_at is None),
        *(o for o in order_blocks if o.direction is bias and o.mitigated_at is None),
    ]
    if not aligned:
        return 0.0
    price_inside = any(a.low <= price <= a.high for a in aligned)
    return weight if price_inside else js_round(weight / 2)


def score_context(
    features: AnalysisFeatures, current_price: float, session_enabled: bool, weights: ScoreWeights
) -> ScoreResult:
    bias = features.bias
    structure = weights.structure if bias is not Bias.NEUTRAL and features.last_structure_shift is not None else 0.0
    liquidity_sweep = weights.liquidity_sweep if features.recently_swept else 0.0
    pd_array = _pd_array_score(bias, current_price, features.fair_value_gaps, features.order_blocks, weights.pd_array)
    session = weights.session if session_enabled else 0.0
    premium_discount = (
        weights.premium_discount
        if (bias is Bias.BULLISH and features.price_location == "discount")
        or (bias is Bias.BEARISH and features.price_location == "premium")
        else 0.0
    )

    breakdown = [
        ScoreComponent(label="Structure", score=structure, max_score=weights.structure),
        ScoreComponent(label="Liquidity", score=liquidity_sweep, max_score=weights.liquidity_sweep),
        ScoreComponent(label="PD arrays", score=pd_array, max_score=weights.pd_array),
        ScoreComponent(label="Session", score=session, max_score=weights.session),
        ScoreComponent(label="Prem/Disc", score=premium_discount, max_score=weights.premium_discount),
    ]

    score = 0.0
    max_score = 0.0
    for component in breakdown:  # added in order, like the TypeScript's reduce
        score += component.score
        max_score += component.max_score
    return ScoreResult(score=score, max_score=max_score, breakdown=breakdown)
