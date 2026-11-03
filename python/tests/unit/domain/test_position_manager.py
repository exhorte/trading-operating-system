"""The Position Manager's rules (ADR 0023): pure, and read from the broker's state — never from a memory."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_os.domain.execution.commands import CommandKind
from trading_os.domain.market.sessions import minutes_until_window_end
from trading_os.domain.positions.manager import (
    ExitPlan,
    ManagedPosition,
    Quote,
    SymbolConstraints,
    WindowState,
    plan_pending_order,
    plan_position,
    r_multiple,
)
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import Side

ACCOUNT = "ACC-A"
CONSTRAINTS = SymbolConstraints(volume_step=0.01, volume_min=0.01, price_decimals=5)
OPEN_WINDOW = WindowState(in_window=True, minutes_to_end=60)
BUFFER = 0.00008  # spread + commission, as a price distance


def position(**overrides: object) -> Position:
    base: dict[str, object] = {
        "position_id": "987",
        "account_id": ACCOUNT,
        "symbol": "EURUSDm",
        "side": Side.BUY,
        "volume": 0.10,
        "entry_price": 1.1000,
        "stop_loss": 1.0990,
        "take_profit": 1.1050,
    }
    base.update(overrides)
    return Position(**base)


def managed(
    pos: Position | None = None, *, initial_stop: float = 1.0990, initial_volume: float = 0.10
) -> ManagedPosition:
    return ManagedPosition(
        position=pos or position(), initial_stop=initial_stop, initial_volume=initial_volume, command_id="cmd-open-1"
    )


def plan_for(
    mp: ManagedPosition,
    bid: float,
    *,
    plan: ExitPlan | None = None,
    window: WindowState = OPEN_WINDOW,
    spread: float = 0.00004,
) -> list:
    return plan_position(mp, Quote(bid=bid, ask=bid + spread), plan or ExitPlan(), window, CONSTRAINTS, BUFFER)


class TestRMultiple:
    def test_r_is_measured_on_the_initial_stop_even_after_the_stop_moved(self) -> None:
        moved = managed(position(stop_loss=1.1000), initial_stop=1.0990)  # stop already at break-even
        assert r_multiple(moved, Quote(bid=1.1010, ask=1.1011)) == pytest.approx(1.0)

    def test_a_short_gains_when_the_ask_falls(self) -> None:
        short = managed(position(side=Side.SELL, stop_loss=1.1010), initial_stop=1.1010)
        assert r_multiple(short, Quote(bid=1.0989, ask=1.0990)) == pytest.approx(1.0)


class TestBreakEven:
    def test_nothing_before_plus_one_r(self) -> None:
        assert plan_for(managed(), 1.1009) == []

    def test_the_stop_goes_to_entry_plus_the_cost_at_plus_one_r(self) -> None:
        (action,) = plan_for(managed(), 1.1010)
        assert action.kind is CommandKind.MODIFY and action.code == "breakeven"
        assert action.stop_loss == pytest.approx(1.10008) and action.position_id == "987"

    def test_it_is_done_once_the_stop_is_there(self) -> None:
        assert plan_for(managed(position(stop_loss=1.10008)), 1.1015) == []

    def test_it_never_loosens_a_stop_that_is_already_better(self) -> None:
        assert plan_for(managed(position(stop_loss=1.1005)), 1.1015) == []

    def test_a_short_mirrors_it(self) -> None:
        short = managed(position(side=Side.SELL, stop_loss=1.1010), initial_stop=1.1010)
        (action,) = plan_for(short, 1.0988)  # ask 1.09884 → R ≈ 1.16
        assert action.code == "breakeven" and action.stop_loss == pytest.approx(1.09992)

    def test_it_can_be_switched_off(self) -> None:
        assert plan_for(managed(), 1.1020, plan=ExitPlan(breakeven_at_r=None)) == []


class TestTrailing:
    PLAN = ExitPlan(trail_distance_r=0.5)

    def test_the_stop_follows_the_price_at_half_an_r(self) -> None:
        (action,) = plan_for(managed(), 1.1030, plan=self.PLAN)
        assert action.code == "trail" and action.stop_loss == pytest.approx(1.1025)

    def test_it_only_tightens(self) -> None:
        assert plan_for(managed(position(stop_loss=1.1026)), 1.1030, plan=self.PLAN) == []

    def test_it_waits_for_break_even_to_be_reached(self) -> None:
        assert plan_for(managed(), 1.1005, plan=self.PLAN) == []

    def test_the_tightest_of_break_even_and_trailing_wins(self) -> None:
        # at +1 R the trail (price − 0.5 R = 1.1005) is tighter than break-even (1.10008)
        (action,) = plan_for(managed(), 1.1010, plan=self.PLAN)
        assert action.code == "trail" and action.stop_loss == pytest.approx(1.1005)


class TestPartialClose:
    PLAN = ExitPlan(partial_at_r=1.0)

    def test_half_of_the_opening_volume_is_taken_at_the_target_r(self) -> None:
        actions = plan_for(managed(position(stop_loss=1.10008)), 1.1010, plan=self.PLAN)
        assert [a.code for a in actions] == ["partial"]
        assert actions[0].kind is CommandKind.PARTIAL_CLOSE and actions[0].volume == pytest.approx(0.05)

    def test_it_is_done_once_the_position_holds_less_than_it_opened_with(self) -> None:
        assert plan_for(managed(position(volume=0.05, stop_loss=1.10008)), 1.1015, plan=self.PLAN) == []

    def test_a_position_that_cannot_be_split_is_left_whole(self) -> None:
        tiny = managed(position(volume=0.01, stop_loss=1.10008), initial_volume=0.01)
        assert plan_for(tiny, 1.1015, plan=self.PLAN) == []

    def test_break_even_and_partial_can_come_in_the_same_cycle(self) -> None:
        actions = plan_for(managed(), 1.1010, plan=self.PLAN)
        assert [a.code for a in actions] == ["breakeven", "partial"]

    def test_the_plan_refuses_a_partial_before_break_even(self) -> None:
        with pytest.raises(ValueError):
            ExitPlan(breakeven_at_r=1.0, partial_at_r=0.5)


class TestEndOfSession:
    def test_the_position_is_closed_before_the_window_ends(self) -> None:
        (action,) = plan_for(managed(), 1.1015, window=WindowState(in_window=True, minutes_to_end=4))
        assert action.kind is CommandKind.CLOSE and action.code == "flat_end_of_window"

    def test_just_outside_the_flat_margin_it_is_still_managed_normally(self) -> None:
        actions = plan_for(managed(), 1.1015, window=WindowState(in_window=True, minutes_to_end=6))
        assert [a.code for a in actions] == ["breakeven"]

    def test_a_position_still_open_outside_the_windows_is_closed(self) -> None:
        (action,) = plan_for(managed(), 1.1000, window=WindowState(in_window=False))
        assert action.code == "flat_outside_window"
        assert (
            plan_for(managed(), 1.1000, window=WindowState(in_window=False), plan=ExitPlan(close_outside_windows=False))
            == []
        )

    def test_minutes_until_the_window_ends(self) -> None:
        assert minutes_until_window_end(datetime(2026, 11, 2, 14, 55, tzinfo=UTC)) == pytest.approx(
            5.0
        )  # 09:55 New York
        assert minutes_until_window_end(datetime(2026, 11, 2, 15, 30, tzinfo=UTC)) is None  # 10:30, between windows
        assert minutes_until_window_end(datetime(2026, 11, 7, 14, 55, tzinfo=UTC)) is None  # a Saturday


class TestUnprotected:
    def test_a_position_without_a_stop_gets_its_opening_stop_back(self) -> None:
        (action,) = plan_for(managed(position(stop_loss=0.0)), 1.1005)
        assert (
            action.code == "protect" and action.kind is CommandKind.MODIFY and action.stop_loss == pytest.approx(1.0990)
        )

    def test_when_the_price_is_already_past_that_stop_it_is_closed(self) -> None:
        (action,) = plan_for(managed(position(stop_loss=0.0)), 1.0985)
        assert action.code == "protect" and action.kind is CommandKind.CLOSE


class TestPendingOrders:
    def order(self) -> PendingOrder:
        return PendingOrder(
            order_id="55",
            account_id=ACCOUNT,
            symbol="EURUSDm",
            side=Side.BUY,
            order_type="limit",
            volume=0.1,
            price=1.0990,
        )

    def test_a_fresh_order_in_the_window_rests(self) -> None:
        assert plan_pending_order(self.order(), ExitPlan(), OPEN_WINDOW, age_minutes=3) is None

    def test_it_is_withdrawn_when_the_window_closes_or_is_closed(self) -> None:
        closing = plan_pending_order(self.order(), ExitPlan(), WindowState(in_window=True, minutes_to_end=2), 3)
        assert closing is not None and closing.kind is CommandKind.CANCEL and closing.order_id == "55"
        outside = plan_pending_order(self.order(), ExitPlan(), WindowState(in_window=False), 3)
        assert outside is not None and outside.code == "cancel_outside_window"

    def test_it_is_withdrawn_when_the_objective_is_reached_before_it_fills(self) -> None:
        # note N6 : « si le marché atteint l'objectif avant de retracer dans le FVG, annuler »
        long = self.order().model_copy(update={"take_profit": 1.1030})
        gone = plan_pending_order(long, ExitPlan(), OPEN_WINDOW, 1, Quote(bid=1.1031, ask=1.1032))
        assert gone is not None and gone.code == "cancel_target_reached" and gone.order_id == "55"
        assert plan_pending_order(long, ExitPlan(), OPEN_WINDOW, 1, Quote(bid=1.1020, ask=1.1021)) is None
        short = self.order().model_copy(update={"side": Side.SELL, "price": 1.1010, "take_profit": 1.0970})
        assert plan_pending_order(short, ExitPlan(), OPEN_WINDOW, 1, Quote(bid=1.0960, ask=1.0969)) is not None
        assert (
            plan_pending_order(short, ExitPlan(), OPEN_WINDOW, 1, Quote(bid=1.0960, ask=1.0975)) is None
        )  # the ask decides a short

    def test_an_order_without_an_objective_or_without_a_quote_is_never_judged_on_it(self) -> None:
        assert plan_pending_order(self.order(), ExitPlan(), OPEN_WINDOW, 1, Quote(bid=2.0, ask=2.0001)) is None
        with_tp = self.order().model_copy(update={"take_profit": 1.1030})
        assert plan_pending_order(with_tp, ExitPlan(), OPEN_WINDOW, 1, None) is None

    def test_it_is_withdrawn_when_it_waited_too_long(self) -> None:
        stale = plan_pending_order(self.order(), ExitPlan(pending_max_age_minutes=30), OPEN_WINDOW, 31)
        assert stale is not None and stale.code == "cancel_stale"
