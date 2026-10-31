"""After-the-fact compliance (T07), ported from ``lib/compliance`` — same vectors, same honest nulls. The one deliberate change:
« session » is judged with the account's trading windows (the user's killzones, New York time), the predicate the live session
gate uses, instead of fixed UTC buckets."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_os.domain.journal.compliance import (
    compliance_rate,
    detect_lockout_violation,
    detect_session_violation,
    detect_size_violation,
    evaluate_trade,
    r_multiple,
    summarize_compliance,
)
from trading_os.domain.journal.models import JournalTrade, Violation, ViolationType
from trading_os.domain.market.models import SymbolSpec
from trading_os.domain.market.sessions import DEFAULT_TRADING_WINDOWS
from trading_os.domain.primitives import Side
from trading_os.domain.risk.lockout import LockoutWindow


def utc(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, second, tzinfo=UTC)


KILL_SWITCH = LockoutWindow(
    lockout_id="lockout-case-1",
    reason="Kill switch manuel",
    since=utc(15, 9, 34, 44),
    until=None,
    cleared_at=utc(15, 9, 37, 18),
)
EURUSD = SymbolSpec(
    name="EURUSD", currency_base="EUR", currency_profit="USD", digits=5, point=0.00001, tick_size=0.00001,
    tick_value=1.0, contract_size=100_000, volume_min=0.01, volume_max=100, volume_step=0.01,
)  # fmt: skip


class TestLockoutViolation:
    """The real case that was the fiche's own success criterion: a trade opened inside an active kill-switch lockout."""

    def test_flags_a_trade_opened_during_the_active_lockout(self) -> None:
        found = detect_lockout_violation(utc(15, 9, 36), [KILL_SWITCH])
        assert found is not None and found.type is ViolationType.LOCKOUT_ACTIVE
        assert "Kill switch manuel" in found.detail and "lockout-case-1" in found.detail

    def test_not_before_it_started_nor_after_it_was_cleared(self) -> None:
        assert detect_lockout_violation(utc(15, 9, 30), [KILL_SWITCH]) is None
        assert detect_lockout_violation(utc(15, 9, 40), [KILL_SWITCH]) is None

    def test_a_timed_pause_covers_its_window_only(self) -> None:
        pause = LockoutWindow(lockout_id="p", reason="Pertes consécutives", since=utc(16, 10), until=utc(16, 10, 30))
        assert detect_lockout_violation(utc(16, 10, 15), [pause]) is not None
        assert detect_lockout_violation(utc(16, 10, 31), [pause]) is None
        assert detect_lockout_violation(utc(16, 10, 30), [pause]) is None  # the end is exclusive: it had expired

    def test_an_uncleared_acknowledgement_lockout_never_expires(self) -> None:
        open_ended = LockoutWindow(lockout_id="k", reason="Kill switch manuel", since=utc(15, 9))
        assert detect_lockout_violation(utc(20, 9), [open_ended]) is not None

    def test_no_lockout_no_violation(self) -> None:
        assert detect_lockout_violation(utc(15, 9, 36), []) is None


class TestSessionViolation:
    def test_inside_a_killzone_is_fine(self) -> None:
        assert detect_session_violation(utc(15, 12), DEFAULT_TRADING_WINDOWS) is None  # 08:00 New York (EDT)
        assert detect_session_violation(utc(15, 7), DEFAULT_TRADING_WINDOWS) is None  # 03:00 New York: London killzone

    def test_overnight_and_afternoon_are_outside(self) -> None:
        asia = detect_session_violation(utc(15, 1), DEFAULT_TRADING_WINDOWS)  # 21:00 New York the evening before
        assert asia is not None and asia.type is ViolationType.SESSION_WINDOW and "New York" in asia.detail
        assert detect_session_violation(utc(15, 17), DEFAULT_TRADING_WINDOWS) is not None  # 13:00 New York

    def test_a_weekend_is_never_open(self) -> None:
        assert detect_session_violation(utc(19, 12), DEFAULT_TRADING_WINDOWS) is not None  # Saturday 08:00 New York

    def test_it_follows_new_york_across_daylight_saving_time(self) -> None:
        winter = datetime(2026, 1, 6, 12, 0, tzinfo=UTC)  # 07:00 EST: the killzone has just opened
        summer = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)  # 08:00 EDT
        assert detect_session_violation(winter, DEFAULT_TRADING_WINDOWS) is None
        assert detect_session_violation(summer, DEFAULT_TRADING_WINDOWS) is None
        assert detect_session_violation(datetime(2026, 1, 6, 11, 59, tzinfo=UTC), DEFAULT_TRADING_WINDOWS) is not None

    def test_the_accounts_own_windows_are_what_is_judged(self) -> None:
        assert detect_session_violation(utc(15, 17), []) is not None  # a account with no window trades nowhere


class TestSizeViolation:
    balance = 10_000.0

    def judge(self, volume: float, stop: float = 1.1490) -> Violation | None:
        return detect_size_violation(
            volume=volume, entry_price=1.1500, stop_loss=stop, balance=self.balance, max_risk_percent=1.0, spec=EURUSD
        )

    def test_within_the_budget(self) -> None:
        # risk 100; 0.0010 stop = 100 ticks × 1.0 = 100 per lot → max 1.00 lot
        assert self.judge(0.5) is None

    def test_clearly_over_the_budget(self) -> None:
        found = self.judge(5.0)
        assert found is not None and found.type is ViolationType.SIZE_POLICY
        assert "5.00 lot" in found.detail and "1% risk budget" in found.detail

    def test_the_rounding_tolerance_does_not_false_positive(self) -> None:
        assert self.judge(1.0) is None and self.judge(1.04) is None and self.judge(1.06) is not None

    def test_no_stop_is_not_judged(self) -> None:
        assert self.judge(5.0, stop=0.0) is None  # 0 is MT5's « unset »

    def test_a_symbol_without_a_tick_value_is_not_judged(self) -> None:
        blind = EURUSD.model_copy(update={"tick_value": 0.0, "tick_value_loss": None})
        assert (
            detect_size_violation(
                volume=50, entry_price=1.15, stop_loss=1.149, balance=1e4, max_risk_percent=1.0, spec=blind
            )
            is None
        )

    def test_it_uses_the_loss_side_tick_value_the_broker_reports(self) -> None:
        pricey = EURUSD.model_copy(update={"tick_value_loss": 2.0})  # twice the risk per lot → half the volume allowed
        found = detect_size_violation(
            volume=0.6, entry_price=1.15, stop_loss=1.149, balance=1e4, max_risk_percent=1.0, spec=pricey
        )
        assert found is not None


def trade(**overrides: object) -> JournalTrade:
    base: dict[str, object] = {
        "broker_position_id": "1000000001", "symbol": "EURUSD", "side": Side.BUY, "volume": 0.05,
        "entry_price": 1.15339, "exit_price": 1.15439, "realized_pnl": 5.0, "stop_loss": 0.0,
        "opened_at": utc(15, 9, 36), "closed_at": utc(15, 9, 37), "has_capture": True,
    }  # fmt: skip
    base.update(overrides)
    return JournalTrade.model_validate(base)


class TestEvaluateTrade:
    def judge(self, t: JournalTrade, lockouts: list[LockoutWindow] | None = None, **kw: object) -> list[Violation]:
        options: dict[str, object] = {"balance": 10_000.0, "max_risk_percent": 1.0, "spec": EURUSD}
        options.update(kw)
        return evaluate_trade(t, lockouts or [], DEFAULT_TRADING_WINDOWS, **options)  # type: ignore[arg-type]

    def test_the_real_case_comes_back_with_its_lockout_violation_and_nothing_else(self) -> None:
        # 09:36Z is 05:36 New York: outside the killzones — and inside the kill-switch lockout. Both are true of that trade.
        found = self.judge(
            trade(opened_at=utc(15, 12, 36)),
            [KILL_SWITCH.model_copy(update={"since": utc(15, 12, 30), "cleared_at": utc(15, 12, 40)})],
        )
        assert [v.type for v in found] == [
            ViolationType.LOCKOUT_ACTIVE
        ]  # stop 0: no size check; 08:36 New York: in session

    def test_an_unknown_opening_time_judges_nothing_instead_of_passing(self) -> None:
        assert self.judge(trade(opened_at=None), [KILL_SWITCH]) == []

    def test_both_a_lockout_and_a_session_violation_can_apply(self) -> None:
        night = LockoutWindow(lockout_id="night", reason="Daily loss guard", since=utc(16, 0))
        found = self.judge(trade(opened_at=utc(16, 1), entry_price=None, stop_loss=None), [night])
        assert sorted(v.type for v in found) == [ViolationType.LOCKOUT_ACTIVE, ViolationType.SESSION_WINDOW]

    def test_the_size_check_needs_a_balance_a_specification_and_a_recorded_stop(self) -> None:
        big = trade(opened_at=utc(15, 12), volume=50, entry_price=1.15, stop_loss=1.149)
        assert [v.type for v in self.judge(big)] == [ViolationType.SIZE_POLICY]
        assert self.judge(big, balance=None) == []
        assert self.judge(big, spec=None) == []
        assert self.judge(trade(opened_at=utc(15, 12), volume=50, entry_price=None, stop_loss=None)) == []


class TestRate:
    def test_empty_and_clean_weeks_score_one(self) -> None:
        assert compliance_rate([]) == 1.0 and compliance_rate([[], [], []]) == 1.0

    def test_it_is_the_share_of_clean_trades(self) -> None:
        v = [Violation(type=ViolationType.LOCKOUT_ACTIVE, detail="x")]
        assert compliance_rate([[], v, [], []]) == 0.75 and compliance_rate([v, v]) == 0.0


class TestSummary:
    def test_it_counts_and_groups_what_evaluate_trade_judged(self) -> None:
        trades = [
            trade(broker_position_id="a", opened_at=utc(15, 12)),  # clean
            trade(broker_position_id="b", opened_at=utc(15, 12, 35), stop_loss=0.0),  # inside the lockout below
            trade(broker_position_id="c", opened_at=utc(15, 17)),  # 13:00 New York: out of session
            trade(broker_position_id="d", opened_at=utc(15, 12), volume=50, entry_price=1.15, stop_loss=1.149),
        ]
        lockout = LockoutWindow(
            lockout_id="L", reason="Kill switch manuel", since=utc(15, 12, 30), cleared_at=utc(15, 12, 40)
        )
        summary = summarize_compliance(
            trades, [lockout], DEFAULT_TRADING_WINDOWS, balance=10_000.0, max_risk_percent=1.0, specs={"EURUSD": EURUSD}
        )
        assert summary.trade_count == 4 and summary.breached_count == 3 and summary.rate == 0.25
        assert summary.by_type == {
            ViolationType.LOCKOUT_ACTIVE: 1, ViolationType.SESSION_WINDOW: 1, ViolationType.SIZE_POLICY: 1,
        }  # fmt: skip
        assert summary.by_trade["a"] == [] and len(summary.by_trade["c"]) == 1

    def test_no_trades_is_a_perfect_empty_week(self) -> None:
        summary = summarize_compliance([], [], DEFAULT_TRADING_WINDOWS, balance=None, max_risk_percent=1.0, specs={})
        assert (summary.rate, summary.trade_count, summary.breached_count) == (1.0, 0, 0)
        assert all(count == 0 for count in summary.by_type.values())


class TestRMultiple:
    def test_what_came_back_in_units_of_risk(self) -> None:
        win = trade(entry_price=1.1500, stop_loss=1.1490, exit_price=1.1520)
        assert r_multiple(win) == 2.0
        loss = trade(entry_price=1.1500, stop_loss=1.1490, exit_price=1.1490)
        assert r_multiple(loss) == -1.0

    def test_a_short_is_measured_the_other_way(self) -> None:
        short = trade(side=Side.SELL, entry_price=1.1500, stop_loss=1.1510, exit_price=1.1480)
        assert r_multiple(short) == 2.0

    def test_no_recorded_stop_or_entry_means_no_r(self) -> None:
        assert r_multiple(trade(stop_loss=0.0)) is None
        assert r_multiple(trade(stop_loss=None)) is None
        assert r_multiple(trade(entry_price=None, stop_loss=1.149)) is None
        assert r_multiple(trade(entry_price=1.15, stop_loss=1.15)) is None
