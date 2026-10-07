"""Port of ``tools/mt5-observer/test_mt5_observer.py`` (the pure parts) + the server-clock fixes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_os.domain.primitives import Side
from trading_os.infrastructure.mt5.observer_logic import (
    DEAL_ENTRY_IN,
    DEAL_ENTRY_OUT,
    DEAL_TYPE_BUY,
    DEAL_TYPE_SELL,
    Deal,
    closed_fact,
    diff_position_ids,
    measure_server_offset_minutes,
    missed_round_trip_ids,
    opened_fact_from_deal,
    scan_window,
    server_time_to_utc,
    sum_realized_pnl,
    utc_to_server_epoch,
    weighted_exit_price,
)


def deal(
    entry: int,
    type_: int,
    volume: float,
    profit: float,
    commission: float,
    swap: float,
    time: int,
    symbol: str = "XAUUSDm",
    price: float = 0.0,
    position_id: int = 0,
) -> Deal:
    return Deal(
        entry=entry,
        type=type_,
        volume=volume,
        profit=profit,
        commission=commission,
        swap=swap,
        time=time,
        symbol=symbol,
        price=price,
        position_id=position_id,
    )


class TestSumRealizedPnl:
    def test_net_winner_despite_a_negative_partial_exit(self) -> None:
        """One entry + two partial exits: the last exit alone is negative after swap, the position is a net winner.
        Judging by a single deal would misclassify it — the sum must not (T02b pitfall)."""
        deals = [
            deal(DEAL_ENTRY_IN, DEAL_TYPE_BUY, 0.02, 0, -0.20, 0, 1_000),
            deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.01, 5.00, -0.10, 0, 1_010),
            deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.01, 0.05, -0.10, -0.20, 1_020),
        ]
        last = deals[-1]
        assert last.profit + last.commission + last.swap < 0  # the trap is real
        assert sum_realized_pnl(deals) == 4.45

    def test_net_loser_stays_a_loser(self) -> None:
        deals = [
            deal(DEAL_ENTRY_IN, DEAL_TYPE_SELL, 0.01, 0, -0.10, 0, 2_000),
            deal(DEAL_ENTRY_OUT, DEAL_TYPE_SELL, 0.01, -3.00, -0.10, -0.05, 2_010),
        ]
        assert sum_realized_pnl(deals) == -3.25


class TestWeightedExitPrice:
    def test_volume_weights_the_average_across_partial_exits(self) -> None:
        exits = [
            deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.01, 5.0, -0.1, 0, 1_010, price=4055.0),
            deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.03, 0.05, -0.1, -0.2, 1_020, price=4053.0),
        ]
        assert weighted_exit_price(exits) == 4053.5  # (4055×0.01 + 4053×0.03) ÷ 0.04

    def test_a_single_exit_is_just_its_price(self) -> None:
        assert (
            weighted_exit_price([deal(DEAL_ENTRY_OUT, DEAL_TYPE_SELL, 0.02, -3.0, -0.1, 0, 2_010, price=4040.0)])
            == 4040.0
        )

    def test_zero_volume_falls_back_to_the_first_price(self) -> None:
        assert weighted_exit_price([deal(DEAL_ENTRY_OUT, DEAL_TYPE_SELL, 0.0, 0, 0, 0, 1, price=1.5)]) == 1.5
        assert weighted_exit_price([]) == 0.0


class TestClosedFact:
    def test_maps_side_symbol_volume_pnl_exit_price_and_close_time(self) -> None:
        deals = [
            deal(DEAL_ENTRY_IN, DEAL_TYPE_BUY, 0.02, 0, -0.20, 0, 1_000, price=4050.0),
            deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.01, 5.00, -0.10, 0, 1_010, price=4055.0),
            deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.01, 0.05, -0.10, -0.20, 1_020, price=4053.0),
        ]
        fact = closed_fact(12345, deals, 0)
        assert fact is not None
        assert (fact.position_id, fact.symbol, fact.side, fact.volume) == ("12345", "XAUUSDm", Side.BUY, 0.02)
        assert fact.realized_pnl == 4.45 and fact.exit_price == 4054.0
        assert fact.closed_at == datetime.fromtimestamp(1_020, UTC)

    def test_a_half_known_history_emits_nothing(self) -> None:
        only_entry = [deal(DEAL_ENTRY_IN, DEAL_TYPE_BUY, 0.02, 0, 0, 0, 1_000)]
        assert closed_fact(1, only_entry, 0) is None
        assert closed_fact(1, [], 0) is None
        assert closed_fact(1, [deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.02, 1, 0, 0, 1_000)], 0) is None

    def test_the_close_time_is_converted_from_the_broker_clock(self) -> None:
        # FTMO's server is UTC+3 in summer: 2026-07-14 15:00 on its clock is 12:00 UTC.
        server_clock = int(datetime(2026, 7, 14, 15, 0, tzinfo=UTC).timestamp())
        deals = [
            deal(DEAL_ENTRY_IN, DEAL_TYPE_BUY, 0.1, 0, 0, 0, server_clock - 600),
            deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.1, 1, 0, 0, server_clock),
        ]
        fact = closed_fact(1, deals, 180)
        assert fact is not None and fact.closed_at == datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class TestOpenedFromDeal:
    def test_maps_from_the_entry_deal_alone_with_unknown_stop_and_target(self) -> None:
        entry = deal(DEAL_ENTRY_IN, DEAL_TYPE_SELL, 0.02, 0, -0.2, 0, 1_500, price=4070.0)
        fact = opened_fact_from_deal(777, entry, 0)
        assert (fact.position_id, fact.side, fact.entry_price) == ("777", Side.SELL, 4070.0)
        assert (fact.stop_loss, fact.take_profit, fact.reconstructed) == (0.0, 0.0, True)
        assert fact.opened_at == datetime.fromtimestamp(1_500, UTC)  # the real fill time, not detection time


class TestPositionDiff:
    def test_opened_and_closed_ids(self) -> None:
        assert diff_position_ids({"1", "2"}, {"2", "3"}) == ({"3"}, {"1"})

    def test_does_not_special_case_a_baseline(self) -> None:
        assert diff_position_ids(set(), {"1"}) == ({"1"}, set())

    def test_identifiers_not_tickets_are_what_the_diff_sees(self) -> None:
        # Same identifier, rewritten ticket: no false close and no false open.
        assert diff_position_ids({"999"}, {"999"}) == (set(), set())


class TestMissedRoundTrips:
    exit_deal = deal(DEAL_ENTRY_OUT, DEAL_TYPE_BUY, 0.01, 2.0, -0.1, 0, 1_005, position_id=777)
    entry_deal = deal(DEAL_ENTRY_IN, DEAL_TYPE_BUY, 0.01, 0, -0.1, 0, 1_000, position_id=777)

    def test_a_position_opened_and_closed_between_two_polls_is_found(self) -> None:
        assert missed_round_trip_ids([self.entry_deal, self.exit_deal], set(), set()) == {"777"}

    def test_a_position_the_normal_diff_already_covers_is_ignored(self) -> None:
        assert missed_round_trip_ids([self.exit_deal], {"777"}, set()) == set()

    def test_a_partial_close_on_a_still_open_position_is_not_a_round_trip(self) -> None:
        assert missed_round_trip_ids([self.exit_deal], set(), {"777"}) == set()

    def test_entries_alone_are_not_exits(self) -> None:
        assert missed_round_trip_ids([self.entry_deal], set(), set()) == set()


class TestServerClock:
    def test_a_fresh_tick_measures_the_offset_rounded_to_half_hours(self) -> None:
        now = 1_800_000_000.0
        assert measure_server_offset_minutes(now + 10_800 + 7, now) == 180  # UTC+3 and 7 s of latency
        assert measure_server_offset_minutes(now - 3, now) == 0
        assert measure_server_offset_minutes(now + 19_800 + 40, now) == 330  # +5:30
        assert measure_server_offset_minutes(now - 18_000, now) == -300

    def test_a_stale_tick_measures_nothing(self) -> None:
        # Saturday: the last tick is a day old. The old estimate returned that gap as if it were an offset.
        now = 1_800_000_000.0
        assert measure_server_offset_minutes(now - 86_400, now) is None
        assert measure_server_offset_minutes(now - 3 * 86_400, now) is None

    def test_round_trip_between_the_two_clocks(self) -> None:
        utc = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        for offset in (0, 120, 180, -300, 330):
            assert server_time_to_utc(utc_to_server_epoch(utc, offset), offset) == utc

    def test_scan_window(self) -> None:
        now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        assert scan_window(now - timedelta(seconds=2), now) == (now - timedelta(seconds=2), now)
        assert scan_window(None, now) == (
            now - timedelta(seconds=10),
            now,
        )  # first poll: only a moment back, not all history
        assert scan_window(now, now) is None and scan_window(now + timedelta(seconds=5), now) is None
