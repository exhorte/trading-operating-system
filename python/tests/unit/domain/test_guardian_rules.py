"""The Account Guardian's judgement (ADR 0025): exits and messages, never an entry, never a position that is not the core's."""

from __future__ import annotations

from trading_os.domain.guardian.rules import GuardianInputs, GuardianPlan, LimitUse, breached_limits, judge
from trading_os.domain.positions.models import Position
from trading_os.domain.primitives import Side

PLAN = GuardianPlan()


def position(position_id: str, *, stop: float = 1.0990) -> Position:
    return Position(
        position_id=position_id, account_id="ACC", symbol="EURUSDm", side=Side.BUY, volume=0.1, entry_price=1.1,
        stop_loss=stop,
    )  # fmt: skip


def limits(daily: float = 0.0, weekly: float = 0.0, total: float = 0.0) -> list[LimitUse]:
    return [
        LimitUse(name="daily loss", used_percent=daily, limit_percent=5.0),
        LimitUse(name="weekly loss", used_percent=weekly, limit_percent=10.0),
        LimitUse(name="total loss", used_percent=total, limit_percent=10.0),
    ]


def inputs(**changes: object) -> GuardianInputs:
    base: dict[str, object] = {"limits": limits(), "managed": [position("1")], "external": []}
    base.update(changes)
    return GuardianInputs(**base)


def test_nothing_to_say_when_every_limit_has_room_and_every_position_has_a_stop() -> None:
    verdict = judge(inputs(limits=limits(daily=2.0, weekly=3.0, total=1.0)), PLAN)
    assert verdict.quiet and not verdict.flatten_all


def test_a_limit_reached_flattens_the_positions_of_the_core() -> None:
    for kwargs, name in (
        ({"daily": 5.0}, "daily loss"),
        ({"weekly": 10.0}, "weekly loss"),
        ({"total": 10.0}, "total loss"),
    ):
        verdict = judge(inputs(limits=limits(**kwargs)), PLAN)
        assert verdict.flatten_all and name in verdict.breached[0]


def test_just_under_the_limit_does_nothing() -> None:
    assert not judge(inputs(limits=limits(daily=4.99)), PLAN).flatten_all


def test_the_user_may_ask_for_a_margin_before_the_limit() -> None:
    early = GuardianPlan(flatten_at_fraction=0.9)
    assert judge(inputs(limits=limits(daily=4.5)), early).flatten_all
    assert not judge(inputs(limits=limits(daily=4.4)), early).flatten_all


def test_a_limit_that_is_not_set_measures_nothing() -> None:
    assert breached_limits([LimitUse(name="daily loss", used_percent=9.0, limit_percent=0.0)], PLAN) == []


def test_with_nothing_of_the_core_open_there_is_nothing_to_flatten() -> None:
    verdict = judge(inputs(limits=limits(daily=5.0), managed=[]), PLAN)
    assert not verdict.flatten_all and verdict.breached


def test_a_position_that_is_not_the_cores_is_only_reported() -> None:
    verdict = judge(inputs(limits=limits(daily=5.0), external=[position("9")]), PLAN)
    assert verdict.flatten_all and len(verdict.alerts) == 1 and "9" in verdict.alerts[0]
    assert judge(inputs(external=[position("9")]), PLAN).quiet  # no limit reached: nothing to say about it


def test_a_position_without_a_stop_has_a_grace_period_then_is_closed() -> None:
    naked = position("2", stop=0.0)
    waiting = judge(inputs(managed=[naked], unprotected_for_seconds={"2": 10.0}), PLAN)
    assert waiting.close_without_stop == [] and len(waiting.alerts) == 1
    overdue = judge(inputs(managed=[naked], unprotected_for_seconds={"2": 30.0}), PLAN)
    assert overdue.close_without_stop == ["2"]
    protected = judge(inputs(managed=[position("2")], unprotected_for_seconds={"2": 500.0}), PLAN)
    assert protected.close_without_stop == []


def test_a_breach_takes_over_from_the_missing_stop_rule() -> None:
    verdict = judge(
        inputs(limits=limits(total=10.0), managed=[position("2", stop=0.0)], unprotected_for_seconds={"2": 99.0}), PLAN
    )
    assert verdict.flatten_all and verdict.close_without_stop == []
