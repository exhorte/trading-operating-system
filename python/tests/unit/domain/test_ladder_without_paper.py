"""ADR 0041, increment 1 — the PAPER mode is gone. The ladder is OFF → OBSERVE → CONFIRM → ARMED → AUTONOMOUS (+ HALTED); an order leaves for the broker or is not made.

Nothing here weakens a guard: OBSERVE stays the « no order » rung, and every rung above it still needs its own conditions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

import trading_os
from trading_os.app.config import Settings, TradingMode
from trading_os.domain.autonomy.plan_modes import PlanMode
from trading_os.domain.autonomy.state import LADDER, AutonomyMode, ExecutionRoute, route_for
from trading_os.domain.system.startup import START_TARGETS

CORE = Path(trading_os.__file__).parent


def test_the_ladder_has_no_paper_rung() -> None:
    assert "PAPER" not in {mode.value for mode in AutonomyMode}
    assert [mode.value for mode in LADDER] == ["OFF", "OBSERVE", "CONFIRM", "ARMED", "AUTONOMOUS"]


def test_there_is_no_simulated_route_every_mode_records_confirms_or_sends() -> None:
    assert {route.value for route in ExecutionRoute} == {"none", "confirm", "automatic"}
    assert route_for(AutonomyMode.OBSERVE) is ExecutionRoute.NONE
    assert route_for(AutonomyMode.CONFIRM) is ExecutionRoute.CONFIRM
    assert route_for(AutonomyMode.ARMED) is ExecutionRoute.AUTOMATIC


def test_the_plan_names_no_paper_mode() -> None:
    assert "PAPER" not in {mode.value for mode in PlanMode}


def test_starting_the_system_climbs_to_observe_or_confirm_at_most() -> None:
    assert START_TARGETS == (AutonomyMode.OBSERVE, AutonomyMode.CONFIRM)


def test_the_ceiling_setting_has_no_paper_and_an_old_value_is_refused_with_what_to_do() -> None:
    assert "PAPER" not in {mode.value for mode in TradingMode}
    with pytest.raises(ValidationError) as refused:
        Settings(_env_file=None, trading_mode="PAPER")  # type: ignore[call-arg]
    message = str(refused.value)
    assert "PAPER" in message and "ADR 0041" in message and "OBSERVE" in message and "CONFIRM" in message


def test_no_module_of_the_core_defines_or_uses_a_simulated_fill() -> None:
    pattern = re.compile(r"PaperSender|ExecutionRoute\.PAPER|AutonomyMode\.PAPER|PlanMode\.PAPER|TradingMode\.PAPER")
    offenders = {
        str(path.relative_to(CORE))
        for path in CORE.rglob("*.py")
        if "(" not in path.name and pattern.search(path.read_text(encoding="utf-8"))
    }
    assert not offenders, offenders
