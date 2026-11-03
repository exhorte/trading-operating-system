"""The ladder of the plan (§18) read on the ladder of the repository (ADR 0034).

The plan names six modes — OBSERVE, PAPER, CONFIRM, DEMO_AUTO, LIVE_CONFIRM, LIVE_AUTO. The repository climbs OFF → OBSERVE → PAPER
→ CONFIRM → ARMED → AUTONOMOUS (+ HALTED). The two are the same ladder seen with the account's environment on: a CONFIRM on a real
account is LIVE_CONFIRM, an automatic rung on a demo is DEMO_AUTO and on a real account LIVE_AUTO. This module is a **reading**: it
adds, renames and removes no state, and nothing in the core switches on it.
"""

from __future__ import annotations

from enum import StrEnum

from trading_os.domain.accounts.models import Environment
from trading_os.domain.autonomy.state import AUTOMATIC_MODES, AutonomyMode
from trading_os.domain.primitives import DomainModel


class PlanMode(StrEnum):
    OFF = "OFF"  # not in the plan: the system is stopped
    OBSERVE = "OBSERVE"
    PAPER = "PAPER"
    CONFIRM = "CONFIRM"
    DEMO_AUTO = "DEMO_AUTO"
    LIVE_CONFIRM = "LIVE_CONFIRM"
    LIVE_AUTO = "LIVE_AUTO"
    HALTED = "HALTED"  # not in the plan: new entries cut


class ModeRights(DomainModel):
    """What a mode permits, in words that do not depend on the screen."""

    mode: PlanMode
    sends_orders: bool  # an order can reach the broker
    needs_human_confirmation: bool  # …only after a human gesture on that very order
    needs_green_readiness: bool  # …and the sixteen checks must be green, then and continuously
    real_money: bool


def plan_mode(mode: AutonomyMode, environment: Environment) -> PlanMode:
    """The plan's name for the account's real mode. A demo and a simulated account are not real money."""
    live = environment is Environment.LIVE
    if mode is AutonomyMode.HALTED:
        return PlanMode.HALTED
    if mode is AutonomyMode.CONFIRM:
        return PlanMode.LIVE_CONFIRM if live else PlanMode.CONFIRM
    if mode in AUTOMATIC_MODES:
        return PlanMode.LIVE_AUTO if live else PlanMode.DEMO_AUTO
    return PlanMode(mode.value)  # OFF, OBSERVE, PAPER


def rights(mode: PlanMode) -> ModeRights:
    automatic = mode in {PlanMode.DEMO_AUTO, PlanMode.LIVE_AUTO}
    confirm = mode in {PlanMode.CONFIRM, PlanMode.LIVE_CONFIRM}
    return ModeRights(
        mode=mode,
        sends_orders=automatic or confirm,
        needs_human_confirmation=confirm,
        needs_green_readiness=automatic,
        real_money=mode in {PlanMode.LIVE_CONFIRM, PlanMode.LIVE_AUTO},
    )


# The ladder as the cockpit draws it for an account of this environment, bottom to top.
def ladder(environment: Environment) -> list[ModeRights]:
    live = environment is Environment.LIVE
    steps = [
        PlanMode.OBSERVE,
        PlanMode.PAPER,
        PlanMode.LIVE_CONFIRM if live else PlanMode.CONFIRM,
        PlanMode.LIVE_AUTO if live else PlanMode.DEMO_AUTO,
    ]
    return [rights(step) for step in steps]
