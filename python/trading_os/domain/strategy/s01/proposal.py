"""S01 step 9 — assembles steps 1-8 into a ``SetupProposal``, or stops at the first step that does not hold (port of
``lib/setup/proposal.ts``).

The pre-conditions (session window, NY lunch, calendar, lockouts) are NOT evaluated here: the strategy runtime consumes them from the
Risk Engine's own sources and from ``preconditions``, never duplicated (S01, « Ancrage dans le code »).

``evaluate_setup`` says exactly where the sequence stopped and why — the measurement of ADR 0011 (« l'étape exacte… dit POURQUOI la
machine n'a rien proposé »); ``propose_setup`` is the thin wrapper for callers that only want the proposal.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import Field

from trading_os.domain.market.analysis.models import Swing
from trading_os.domain.market.analysis.pd_arrays import detect_order_blocks
from trading_os.domain.market.analysis.structure import detect_structure_shifts
from trading_os.domain.market.analysis.swings import detect_swings
from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import SessionWindow
from trading_os.domain.primitives import Bias, DomainModel, Side
from trading_os.domain.strategy.s01.bias import daily_bias
from trading_os.domain.strategy.s01.dealing_range import last_dealing_range, location_in_range
from trading_os.domain.strategy.s01.displacement import DisplacementConfig, detect_displacement
from trading_os.domain.strategy.s01.gates import ViabilityGateInput, evaluate_viability_gates
from trading_os.domain.strategy.s01.liquidity import liquidity_pool, opposing_target, sweep_trigger_candidate
from trading_os.domain.strategy.s01.models import (
    BlockedOutcome,
    ProposedOutcome,
    SetupOutcome,
    SetupProposal,
    SetupStage,
)
from trading_os.domain.strategy.s01.poi import PointOfInterest, point_of_interest_for
from trading_os.domain.strategy.s01.stop import compute_stop_loss
from trading_os.domain.strategy.s01.sweep import SweepLevel, detect_sweep
from trading_os.shared.time import iso


class SetupProposalInput(DomainModel):
    symbol: str
    h4_candles: list[Candle]
    d1_candles: list[Candle]
    h1_candles: list[Candle]
    # The 15-minute map (closed bars only, all closed before the reaction window starts): read instead of the 1H series for the
    # dealing range and the liquidity pool by a variant that asks for it (S02, notes N5/N6). Empty for S01.
    map_candles: list[Candle] = Field(default_factory=list)
    # Entry-timeframe (M1) candles BEFORE the reaction window — they map the liquidity and the swing structure a displacement must
    # break. They must NOT include the candle(s) that perform the sweep: the liquidity scan runs forward through whatever series it
    # is given, so a pool computed over candles that already contain the sweep would see the level as « already swept » and reject
    # the very trigger this pipeline is trying to identify. The split mirrors how it runs live: the pool is what is known *before*
    # watching for a sweep, not a replay of the whole outcome at once.
    context_candles: list[Candle]
    # Entry-timeframe (M1) candles from the moment the sweep is watched for, through the displacement.
    reaction_candles: list[Candle]
    swing_lookback: int
    equal_level_tolerance: float
    session_windows: list[SessionWindow]
    atr_period: int
    min_body_atr_multiple: float
    min_fvg_size: float
    spread_buffer: float
    spread: float  # live spread and commission, price units (see gates)
    commission: float
    cost_threshold: float
    min_risk_reward: float
    max_stop_distance: float | None = None
    # decimals kept by the equal highs/lows and previous-day levels: the original's 2 (gold's) unless the caller decides otherwise
    level_decimals: int = 2


def _blocked(stage: SetupStage, detail: str) -> BlockedOutcome:
    return BlockedOutcome(stage=stage, detail=detail)


def _last_opposite_swing(swings: Sequence[Swing], side: Side) -> Swing | None:
    """The most recent context swing of the kind a displacement in ``side``'s direction must break (a buy breaks the last swing
    high, a sell the last swing low)."""
    want_kind = "high" if side is Side.BUY else "low"
    candidates = [s for s in swings if s.kind == want_kind]
    if not candidates:
        return None
    best = candidates[0]
    for swing in candidates[1:]:
        best = best if best.index > swing.index else swing
    return best


def _h4_d1_bias(setup: SetupProposalInput) -> Bias:
    return daily_bias(setup.h4_candles, setup.d1_candles, setup.swing_lookback)


def entry_in_poi(poi: PointOfInterest, side: Side, fraction: float) -> float:
    """The limit price inside the zone of interest: ``fraction`` of the way from the edge price reaches first (the top of a bullish zone,
    the bottom of a bearish one) to the far edge. 0.5 is the CE — returned as ``poi.ce`` itself so S01 stays exact to the bit."""
    if fraction == 0.5:
        return poi.ce
    if side is Side.BUY:
        return poi.high - fraction * (poi.high - poi.low)
    return poi.low + fraction * (poi.high - poi.low)


@dataclass(frozen=True)
class Variant:
    """What a strategy built on this pipeline may change without writing a second detector (ADR 0024). The default is S01 itself."""

    bias: Callable[[SetupProposalInput], Bias] = _h4_d1_bias
    bias_detail: str = "H4/D1 disagree or show no confirmed structure"
    entry_fraction: float = 0.5
    id_prefix: str = "setup"
    # The four rules below are S02's, taken from notes N5 and N6 (07_trading_strategy). All off = S01, to the bit.
    use_map_timeframe: bool = (
        False  # dealing range and liquidity map on the 15-minute series, not 1H / the entry timeframe
    )
    poi_location: bool = False  # N5: the ZONE (not the price) must sit in discount for a buy, premium for a sell
    target_beyond_equilibrium: bool = (
        False  # N5: the target is past the 50 % line of the range (the "low hanging fruit")
    )
    entry_spread_offset: bool = False  # N6: a buy limit rests one spread above the zone's edge so the ask can fill it


S01_VARIANT = Variant()


def evaluate_setup(setup: SetupProposalInput, variant: Variant = S01_VARIANT) -> BlockedOutcome | ProposedOutcome:
    bias = variant.bias(setup)
    if bias is Bias.NEUTRAL:
        return _blocked(SetupStage.BIAS, variant.bias_detail)
    side = Side.BUY if bias is Bias.BULLISH else Side.SELL

    range_candles = setup.map_candles if variant.use_map_timeframe else setup.h1_candles
    label = "15m" if variant.use_map_timeframe else "1H"
    dealing_range = last_dealing_range(range_candles, setup.swing_lookback)
    if dealing_range is None:
        return _blocked(SetupStage.DEALING_RANGE, f"fewer than two {label} swings to anchor a range")
    if not range_candles:
        return _blocked(SetupStage.DEALING_RANGE, f"no {label} candles")
    needed = "discount" if side is Side.BUY else "premium"
    if not variant.poi_location:
        location = location_in_range(range_candles[-1].close, dealing_range)
        if location != needed:
            return _blocked(SetupStage.RANGE_LOCATION, f"price is {location}, need {needed} for a {side.value}")

    context_swings = detect_swings(setup.context_candles, setup.swing_lookback)
    pool_candles = setup.map_candles if variant.use_map_timeframe else setup.context_candles
    pool_swings = detect_swings(pool_candles, setup.swing_lookback) if variant.use_map_timeframe else context_swings
    pool = liquidity_pool(
        pool_candles, pool_swings, setup.equal_level_tolerance, setup.session_windows, setup.level_decimals
    )
    if not setup.context_candles:
        return _blocked(SetupStage.LIQUIDITY, "no context candles")
    reference_price = setup.context_candles[-1].close

    trigger_level = sweep_trigger_candidate(pool, side, reference_price)
    if trigger_level is None:
        return _blocked(SetupStage.LIQUIDITY, "no resting liquidity on the trigger side")
    target = opposing_target(pool, side, reference_price)
    if target is None:
        return _blocked(SetupStage.LIQUIDITY, "no unswept liquidity on the target side")

    sweep = detect_sweep(setup.reaction_candles, SweepLevel(kind=trigger_level.kind, price=trigger_level.price), side)
    if sweep is None:
        return _blocked(SetupStage.SWEEP, "level never touched, or breached without reclaiming")

    opposite_swing = _last_opposite_swing(context_swings, side)
    if opposite_swing is None:
        return _blocked(SetupStage.OPPOSITE_SWING, "no prior swing to break for an MSS")

    sweep_index = next((i for i, c in enumerate(setup.reaction_candles) if c.open_time == sweep.swept_at), -1)
    post_sweep_candles = setup.reaction_candles[sweep_index + 1 :]
    displacement = detect_displacement(
        post_sweep_candles, side, opposite_swing.price,
        DisplacementConfig(
            atr_period=setup.atr_period, min_body_atr_multiple=setup.min_body_atr_multiple,
            min_fvg_size=setup.min_fvg_size,
        ),
    )  # fmt: skip
    if displacement is None:
        return _blocked(SetupStage.DISPLACEMENT, "no body-close break with a big-enough, FVG-backed candle")

    all_candles = [*setup.context_candles, *setup.reaction_candles]
    all_swings = detect_swings(all_candles, setup.swing_lookback)
    structure_shifts = detect_structure_shifts(all_candles, all_swings, setup.swing_lookback)
    order_blocks = detect_order_blocks(all_candles, structure_shifts)
    poi = point_of_interest_for(displacement, order_blocks, side)
    if poi is None:
        return _blocked(SetupStage.POI, "FVG already mitigated and no usable order block")
    if variant.poi_location:
        zone_location = location_in_range(poi.ce, dealing_range)
        if zone_location != needed:
            return _blocked(
                SetupStage.RANGE_LOCATION,
                f"the zone of interest is in {zone_location}, need {needed} for a {side.value}",
            )
    if variant.target_beyond_equilibrium:
        past_half = (
            target.price > dealing_range.equilibrium if side is Side.BUY else target.price < dealing_range.equilibrium
        )
        if not past_half:
            return _blocked(SetupStage.GATES, "the target is not past the 50 % line of the range")

    entry_price = entry_in_poi(poi, side, variant.entry_fraction)
    if variant.entry_spread_offset and side is Side.BUY:
        entry_price += setup.spread
    stop = compute_stop_loss(side, sweep.wick_extreme, setup.spread_buffer, entry_price, setup.max_stop_distance)
    if stop is None:
        return _blocked(SetupStage.STOP, "stop distance exceeds the symbol's calibrated ceiling")

    gate = evaluate_viability_gates(
        ViabilityGateInput(
            entry_price=entry_price, stop_distance=stop.distance, target_price=target.price, side=side,
            spread=setup.spread, commission=setup.commission, cost_threshold=setup.cost_threshold,
            min_risk_reward=setup.min_risk_reward,
        )
    )  # fmt: skip
    if not gate.passed:
        return _blocked(SetupStage.GATES, gate.reason or "viability gate refused")

    return ProposedOutcome(
        proposal=SetupProposal(
            proposal_id=f"{variant.id_prefix}-{setup.symbol}-{iso(displacement.occurred_at)}", symbol=setup.symbol, side=side,
            swept_level_kind=trigger_level.kind, swept_level_price=trigger_level.price, entry_price=entry_price,
            stop_loss=stop.price, take_profit=target.price, cost_ratio=gate.cost_ratio,
            risk_reward_ratio=gate.risk_reward_ratio, detected_at=displacement.occurred_at,
        )
    )  # fmt: skip


def propose_setup(setup: SetupProposalInput, variant: Variant = S01_VARIANT) -> SetupProposal | None:
    """The proposal itself, or ``None`` — for callers that do not care where the sequence stopped."""
    outcome = evaluate_setup(setup, variant)
    return outcome.proposal if isinstance(outcome, ProposedOutcome) else None


__all__ = [
    "S01_VARIANT",
    "SetupOutcome",
    "SetupProposalInput",
    "Variant",
    "entry_in_poi",
    "evaluate_setup",
    "propose_setup",
]
