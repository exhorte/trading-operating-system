"""The Python S01 pipeline against golden vectors generated from the TypeScript original (``tests/golden/s01.json``).

Exact equality, as for the analysis engine: the two implementations do the same IEEE-754 arithmetic in the same order, so a difference is
a porting bug. The end-to-end scenarios include the reference fixture of ``lib/setup/proposal.test.ts`` (a complete buy), its mirror
(a complete sell), single-fault variants for every stage the pipeline can stop at, perturbed copies with random parameters, and
random walks; the unit vectors cover each step on its own.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from trading_os.domain.market.analysis.models import OrderBlock
from trading_os.domain.market.analysis.swings import detect_swings
from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import DEFAULT_SESSION_WINDOWS
from trading_os.domain.primitives import Bias, Side, Timeframe
from trading_os.domain.strategy.s01 import SetupProposalInput, evaluate_setup
from trading_os.domain.strategy.s01.bias import daily_bias
from trading_os.domain.strategy.s01.dealing_range import DealingRange, last_dealing_range, location_in_range
from trading_os.domain.strategy.s01.displacement import DisplacementConfig, DisplacementEvent, detect_displacement
from trading_os.domain.strategy.s01.gates import ViabilityGateInput, evaluate_viability_gates
from trading_os.domain.strategy.s01.liquidity import liquidity_pool, opposing_target, sweep_trigger_candidate
from trading_os.domain.strategy.s01.poi import PointOfInterest, is_invalidated_by_ce, point_of_interest_for
from trading_os.domain.strategy.s01.preconditions import is_in_killzone, is_past_ny_lunch
from trading_os.domain.strategy.s01.reconciliation import AgreementProposal, AgreementTrade, reconcile
from trading_os.domain.strategy.s01.stop import compute_stop_loss
from trading_os.domain.strategy.s01.sweep import SweepLevel, detect_sweep
from trading_os.shared.time import parse_iso

GOLDEN = json.loads((Path(__file__).parents[3] / "golden" / "s01.json").read_text(encoding="utf-8"))
MILLIS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.000Z$")
CANDLE_FIELDS = ("h4Candles", "d1Candles", "h1Candles", "contextCandles", "reactionCandles")


def canon(value: Any) -> Any:
    """JavaScript writes ``…:00.000Z``, pydantic ``…:00Z``; and JSON has no Infinity or NaN (JavaScript writes ``null``)."""
    if isinstance(value, str):
        match = MILLIS.match(value)
        return f"{match.group(1)}Z" if match else value
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [canon(v) for v in value]
    if isinstance(value, dict):
        return {k: canon(v) for k, v in value.items()}
    return value


def dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return canon(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, list):
        return [dump(v) for v in value]
    return value


def unpack(packed: dict[str, Any]) -> list[Candle]:
    return [
        Candle(
            symbol=packed["s"],
            timeframe=Timeframe(packed["tf"]),
            open_time=parse_iso(row[0]),
            open=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
            closed=bool(row[6]),
        )
        for row in packed["rows"]
    ]


def build_input(raw: dict[str, Any]) -> SetupProposalInput:
    data = dict(raw)
    for key in CANDLE_FIELDS:
        data[key] = unpack(raw[key])
    return SetupProposalInput.model_validate(data)


SCENARIOS: list[dict[str, Any]] = GOLDEN["scenarios"]


def named(items: list[dict[str, Any]]) -> list[str]:
    return [item["name"] for item in items]


# ------------------------------------------------------------------------------------------------------ end to end


def test_the_scenarios_reach_every_stage_the_pipeline_can_stop_at() -> None:
    """A golden file that never reaches a stage cannot vouch for it."""
    outcomes = [s["outcome"] for s in SCENARIOS]
    stages = {o["stage"] for o in outcomes if o["status"] == "blocked"}
    assert stages == {
        "bias", "dealing_range", "range_location", "liquidity", "sweep", "opposite_swing", "displacement", "stop", "gates",
    }  # fmt: skip
    proposed = [o["proposal"] for o in outcomes if o["status"] == "proposed"]
    assert len(proposed) >= 15 and {p["side"] for p in proposed} == {"buy", "sell"}
    assert {p["sweptLevelKind"] for p in proposed} >= {"equal_lows", "equal_highs"}
    assert len({p["entryPrice"] for p in proposed}) > 5  # not one scenario repeated


@pytest.mark.parametrize("scenario", SCENARIOS, ids=named(SCENARIOS))
def test_the_whole_sequence(scenario: dict[str, Any]) -> None:
    outcome = evaluate_setup(build_input(scenario["input"]))
    assert dump(outcome) == canon(scenario["outcome"])


def test_the_reference_fixture_proposes_the_documented_buy() -> None:
    """``lib/setup/proposal.test.ts``: sweeps the equal lows at 99, targets the far equal highs at 105, enters at the CE of the FVG."""
    scenario = next(s for s in SCENARIOS if s["name"] == "buy/base")
    proposal = evaluate_setup(build_input(scenario["input"]))
    assert proposal.status == "proposed"
    assert (proposal.proposal.side, proposal.proposal.swept_level_price, proposal.proposal.take_profit) == (
        Side.BUY,
        99,
        105,
    )
    assert proposal.proposal.entry_price == pytest.approx(99.85) and proposal.proposal.stop_loss == pytest.approx(98.65)
    assert proposal.proposal.cost_ratio == pytest.approx(0.1, abs=0.005) and proposal.proposal.risk_reward_ratio >= 3


# ------------------------------------------------------------------------------------------------------ the steps


@pytest.mark.parametrize("index", range(len(GOLDEN["bias"])))
def test_daily_bias(index: int) -> None:
    case = GOLDEN["bias"][index]
    assert daily_bias(unpack(case["h4"]), unpack(case["d1"]), case["lookback"]).value == case["bias"]


def test_daily_bias_vectors_are_not_all_neutral() -> None:
    assert {c["bias"] for c in GOLDEN["bias"]} == {"bullish", "bearish", "neutral"}


@pytest.mark.parametrize("index", range(len(GOLDEN["dealingRange"])))
def test_dealing_range_and_its_location(index: int) -> None:
    case = GOLDEN["dealingRange"][index]
    found = last_dealing_range(unpack(case["candles"]), case["lookback"])
    assert dump(found) == case["range"]
    for probe in case["locations"]:
        if probe is None:
            assert found is None
        else:
            assert found is not None and location_in_range(probe["price"], found) == probe["location"]
    assert (
        location_in_range(1.1, DealingRange(external_high=1.1, external_low=1.1, equilibrium=1.1)) == case["degenerate"]
    )


def test_dealing_range_vectors_cover_both_sides_and_the_absence_of_a_range() -> None:
    cases = GOLDEN["dealingRange"]
    assert any(c["range"] is None for c in cases) and any(c["range"] is not None for c in cases)
    assert {p["location"] for c in cases for p in c["locations"] if p} == {"premium", "discount", "equilibrium"}


@pytest.mark.parametrize("index", range(len(GOLDEN["liquidity"])))
def test_the_liquidity_pool_and_its_picks(index: int) -> None:
    case = GOLDEN["liquidity"][index]
    candles = unpack(case["candles"])
    swings = detect_swings(candles, case["lookback"])
    pool = liquidity_pool(candles, swings, case["tolerance"], DEFAULT_SESSION_WINDOWS)
    assert dump(pool) == canon(case["pool"])
    for pick in case["targets"]:
        side = Side(pick["side"])
        assert dump(opposing_target(pool, side, pick["from"])) == canon(pick["target"])
        assert dump(sweep_trigger_candidate(pool, side, pick["from"])) == canon(pick["trigger"])


def test_liquidity_vectors_include_asia_levels_swept_and_not() -> None:
    levels = [lv for c in GOLDEN["liquidity"] for lv in c["pool"]]
    assert {"session_high", "session_low", "equal_highs", "previous_day_low"} <= {lv["kind"] for lv in levels}
    asia = [lv for lv in levels if lv["kind"] == "session_high"]
    assert any(lv["sweptAt"] for lv in asia) and any(lv["sweptAt"] is None for lv in asia)
    picks = [p for c in GOLDEN["liquidity"] for p in c["targets"]]
    assert any(p["target"] for p in picks) and any(p["target"] is None for p in picks)


@pytest.mark.parametrize("index", range(len(GOLDEN["sweep"])))
def test_sweep(index: int) -> None:
    case = GOLDEN["sweep"][index]
    level = SweepLevel.model_validate(case["level"])
    assert dump(detect_sweep(unpack(case["candles"]), level, Side(case["side"]))) == canon(case["sweep"])


def test_sweep_vectors_include_sweeps_cassures_and_untouched_levels() -> None:
    assert sum(1 for c in GOLDEN["sweep"] if c["sweep"]) >= 8 and sum(1 for c in GOLDEN["sweep"] if not c["sweep"]) >= 8


@pytest.mark.parametrize("index", range(len(GOLDEN["displacement"])))
def test_displacement(index: int) -> None:
    case = GOLDEN["displacement"][index]
    config = DisplacementConfig.model_validate(case["config"])
    found = detect_displacement(unpack(case["candles"]), Side(case["side"]), case["opposite"], config)
    assert dump(found) == canon(case["displacement"])


def test_displacement_vectors_include_hits_and_misses() -> None:
    found = [c["displacement"] for c in GOLDEN["displacement"] if c["displacement"]]
    assert len(found) >= 3 and len(found) < len(GOLDEN["displacement"]) - 3


@pytest.mark.parametrize("index", range(len(GOLDEN["poi"])))
def test_point_of_interest_and_its_invalidation(index: int) -> None:
    case = GOLDEN["poi"][index]
    side = Side(case["side"])
    displacement = DisplacementEvent.model_validate(case["displacement"])
    blocks = [OrderBlock.model_validate(b) for b in case["orderBlocks"]]
    poi = point_of_interest_for(displacement, blocks, side)
    assert dump(poi) == canon(case["poi"])
    probe = poi or PointOfInterest(
        kind="fvg", high=1.11, low=1.1, ce=1.105, formed_at=parse_iso("2026-01-05T00:00:00Z")
    )
    assert is_invalidated_by_ce(probe, side, unpack(case["after"])) is case["invalidated"]


def test_poi_vectors_cover_the_fvg_the_order_block_fallback_and_nothing() -> None:
    kinds = [c["poi"]["kind"] if c["poi"] else None for c in GOLDEN["poi"]]
    assert {"fvg", "order_block", None} <= set(kinds)
    assert {c["invalidated"] for c in GOLDEN["poi"]} == {True, False}


@pytest.mark.parametrize("index", range(len(GOLDEN["stop"])))
def test_stop(index: int) -> None:
    case = GOLDEN["stop"][index]
    found = compute_stop_loss(Side(case["side"]), case["wick"], case["buffer"], case["entry"], case.get("max"))
    assert dump(found) == canon(case["stop"])


def test_stop_vectors_include_refusals_and_acceptances() -> None:
    assert {c["stop"] is None for c in GOLDEN["stop"]} == {True, False}


@pytest.mark.parametrize("index", range(len(GOLDEN["gates"])))
def test_viability_gates(index: int) -> None:
    case = GOLDEN["gates"][index]
    result = evaluate_viability_gates(ViabilityGateInput.model_validate(case["input"]))
    assert dump(result) == canon(case["result"])  # including the wording of the refusal


def test_gate_vectors_include_every_verdict() -> None:
    results = [c["result"] for c in GOLDEN["gates"]]
    assert any(r["passed"] for r in results)
    assert any(r["reason"] and r["reason"].startswith("porte de coût") for r in results)
    assert any(r["reason"] and r["reason"].startswith("porte R:R") for r in results)


# ------------------------------------------------------------------------------------------------------ the calendar and the agreement


def test_killzones_and_the_lunch_cutoff_follow_new_york_time_across_both_dst_changes() -> None:
    vectors = GOLDEN["preconditions"]
    stamps = [parse_iso(s) for s in vectors["stamps"]]
    assert [is_in_killzone(ts) for ts in stamps] == vectors["killzone"]
    assert [is_past_ny_lunch(ts) for ts in stamps] == vectors["pastLunch"]
    assert any(vectors["killzone"]) and not all(vectors["killzone"]) and any(vectors["pastLunch"])
    assert len(stamps) > 1000


@pytest.mark.parametrize("index", range(len(GOLDEN["agreement"])))
def test_agreement_between_proposals_and_trades(index: int) -> None:
    case = GOLDEN["agreement"][index]
    proposals = [AgreementProposal.model_validate(p) for p in case["proposals"]]
    trades = [AgreementTrade.model_validate(t) for t in case["trades"]]
    rows = dump(reconcile(proposals, trades, case["tolerance"]))
    expected = [{("agreement" if k == "class" else k): v for k, v in row.items()} for row in canon(case["rows"])]
    assert rows == expected


def test_agreement_vectors_cover_the_three_classes() -> None:
    classes = {r["class"] for c in GOLDEN["agreement"] for r in c["rows"]}
    assert classes == {"PROPOSE_ET_PRIS", "PROPOSE_ET_REFUSE", "PRIS_SANS_PROPOSITION"}


def test_the_bias_enum_is_what_the_vectors_speak() -> None:
    assert {b.value for b in Bias} == {"bullish", "bearish", "neutral"}
