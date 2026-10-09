"""Lockouts, the trading-day anchor and the loss streak (ported from the former ``lib/risk/lockout.test.ts``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

from trading_os.domain.risk.lockout import (
    CONSECUTIVE_LOSS_REASON,
    KILL_SWITCH_REASON,
    ActiveLockout,
    apply_active_lockout,
    cleared_by_for_ack,
    detect_consecutive_loss_pause,
    detect_new_lockout,
    is_lockout_expired,
)
from trading_os.domain.risk.state import GateResult, RiskMode, RiskState
from trading_os.domain.risk.trading_day import (
    StreakTrade,
    count_consecutive_losses,
    estimate_server_utc_offset_minutes,
    resolve_today_start_utc,
)

NOW = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


def state(
    mode: RiskMode = RiskMode.LOCKED, reason: str | None = "Daily loss guard", gates: list[GateResult] | None = None
) -> RiskState:
    return RiskState(
        account_id="TEST-ACC-1",
        mode=mode,
        daily_loss_used_percent=5.5,
        max_drawdown_used_percent=0.0,
        open_risk_percent=0.0,
        trades_today=3,
        consecutive_losses=0,
        lockout_reason=reason,
        gates=gates or [],
        evaluated_at=NOW,
    )


def lockout(reason: str = "Daily loss guard", until: datetime | None = None, since: datetime = NOW) -> ActiveLockout:
    return ActiveLockout(lockout_id="l1", reason=reason, since=since, until=until)


class TestDetectNewLockout:
    def test_fires_when_just_locked_and_nothing_on_record(self) -> None:
        found = detect_new_lockout(state(), None)
        assert found is not None and found.reason == "Daily loss guard"

    def test_does_not_refire_while_already_recorded(self) -> None:
        assert detect_new_lockout(state(), lockout()) is None

    def test_does_not_fire_for_a_normal_state(self) -> None:
        assert detect_new_lockout(state(RiskMode.NORMAL, None), None) is None


class TestApplyActiveLockout:
    def test_the_ledger_overrides_a_recovered_live_state(self) -> None:
        held = lockout()
        merged = apply_active_lockout(state(RiskMode.NORMAL, None), held, NOW)
        assert merged.mode is RiskMode.LOCKED and merged.lockout_reason == "Daily loss guard"
        assert merged.lockout_id == held.lockout_id  # what an acknowledgement has to name travels with the lock

    def test_passes_through_without_an_active_lockout(self) -> None:
        normal = state(RiskMode.NORMAL, None)
        assert apply_active_lockout(normal, None, NOW) is normal

    def test_an_expired_timed_pause_passes_through(self) -> None:
        normal = state(RiskMode.NORMAL, None)
        expired = lockout(CONSECUTIVE_LOSS_REASON, until=NOW - timedelta(minutes=30))
        assert apply_active_lockout(normal, expired, NOW) is normal

    def test_a_running_timed_pause_still_locks(self) -> None:
        until = NOW + timedelta(minutes=25)
        merged = apply_active_lockout(state(RiskMode.NORMAL, None), lockout(CONSECUTIVE_LOSS_REASON, until=until), NOW)
        assert merged.mode is RiskMode.LOCKED and merged.lockout_until == until


class TestExpiry:
    def test_an_acknowledgement_only_lockout_never_expires(self) -> None:
        assert not is_lockout_expired(lockout(KILL_SWITCH_REASON), NOW + timedelta(days=30))

    def test_a_pause_expires_exactly_at_until(self) -> None:
        assert is_lockout_expired(lockout(CONSECUTIVE_LOSS_REASON, until=NOW), NOW)
        assert not is_lockout_expired(lockout(CONSECUTIVE_LOSS_REASON, until=NOW + timedelta(seconds=1)), NOW)


class TestConsecutiveLossPause:
    blocked: ClassVar[list[GateResult]] = [
        GateResult(gate_id="gate-consec-loss", label="Consecutive losses", state="blocked", detail="2/2")
    ]
    last_loss = datetime(2026, 9, 5, 9, 45, tzinfo=UTC)

    def test_fires_a_30_minute_pause_from_the_last_loss(self) -> None:
        found = detect_consecutive_loss_pause(state(RiskMode.NORMAL, None, self.blocked), None, self.last_loss, 30)
        assert found is not None
        assert found.reason == CONSECUTIVE_LOSS_REASON and found.until == datetime(2026, 9, 5, 10, 15, tzinfo=UTC)

    def test_not_while_any_lockout_is_on_record(self) -> None:
        assert (
            detect_consecutive_loss_pause(state(RiskMode.NORMAL, None, self.blocked), lockout(), self.last_loss, 30)
            is None
        )

    def test_not_when_the_gate_is_open(self) -> None:
        assert detect_consecutive_loss_pause(state(RiskMode.NORMAL, None), None, self.last_loss, 30) is None

    def test_not_without_a_known_last_loss(self) -> None:
        assert detect_consecutive_loss_pause(state(RiskMode.NORMAL, None, self.blocked), None, None, 30) is None


class TestClearedBy:
    def test_kill_switch_keeps_its_audit_value(self) -> None:
        assert cleared_by_for_ack(KILL_SWITCH_REASON) == "kill-switch-ack"

    def test_everything_else_is_manual(self) -> None:
        for reason in ("Daily loss guard", "Max trades/day", CONSECUTIVE_LOSS_REASON):
            assert cleared_by_for_ack(reason) == "manual"


class TestTradingDayAnchor:
    def test_server_midnight_not_utc_midnight(self) -> None:
        # Server at UTC+3: 2026-10-07 20:30Z is 23:30 server time on the 7th → the day began 2026-10-06 21:00Z.
        assert resolve_today_start_utc(datetime(2026, 10, 7, 20, 30, tzinfo=UTC), 180) == datetime(
            2026, 10, 6, 21, 0, tzinfo=UTC
        )

    def test_rolls_over_with_the_server_clock(self) -> None:
        assert resolve_today_start_utc(datetime(2026, 10, 7, 21, 30, tzinfo=UTC), 180) == datetime(
            2026, 10, 7, 21, 0, tzinfo=UTC
        )

    def test_utc_server_and_negative_offsets(self) -> None:
        assert resolve_today_start_utc(datetime(2026, 10, 7, 5, 0, tzinfo=UTC), 0) == datetime(
            2026, 10, 7, 0, 0, tzinfo=UTC
        )
        assert resolve_today_start_utc(datetime(2026, 10, 7, 3, 0, tzinfo=UTC), -300) == datetime(
            2026, 10, 6, 5, 0, tzinfo=UTC
        )

    def test_offset_estimate_is_rounded_to_half_hours(self) -> None:
        assert estimate_server_utc_offset_minutes(1_000_010_807, 1_000_000_000) == 180  # +3 h and 7 s of latency
        assert estimate_server_utc_offset_minutes(1_000_000_000 - 3, 1_000_000_000) == 0
        assert estimate_server_utc_offset_minutes(1_000_000_000 + 19_800 + 40, 1_000_000_000) == 330  # +5:30


class TestLossStreak:
    def t(self, pnl: float, minutes_ago: int) -> StreakTrade:
        return StreakTrade(realized_pnl=pnl, closed_at=NOW - timedelta(minutes=minutes_ago))

    def test_trailing_run_of_losses_most_recent_first(self) -> None:
        count, last = count_consecutive_losses([self.t(-5, 10), self.t(-3, 40), self.t(2, 90), self.t(-1, 120)])
        assert count == 2 and last == NOW - timedelta(minutes=10)

    def test_a_flat_trade_ends_the_streak(self) -> None:
        assert count_consecutive_losses([self.t(0.0, 5), self.t(-3, 40)]) == (0, None)

    def test_no_trades(self) -> None:
        assert count_consecutive_losses([]) == (0, None)
