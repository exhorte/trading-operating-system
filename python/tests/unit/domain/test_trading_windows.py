"""The hours each strategy looks for a setup (ADR 0030): S01 keeps its historical windows, S02 has its own, both are read in New York local
time with the daylight-saving change handled by the zone, and nothing is ever compared across UTC, the MT5 server's clock and New York."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone

import pytest
from pydantic import ValidationError

from trading_os.app.config import Settings
from trading_os.domain.accounts.models import TradingRules
from trading_os.domain.market.sessions import (
    ACCOUNT_TRADING_WINDOWS,
    DEFAULT_TRADING_WINDOWS,
    S01_TRADING_WINDOWS,
    S02_TRADING_WINDOWS,
    TradingWindow,
    describe_trading_windows,
    in_trading_window,
    minutes_until_window_end,
    parse_trading_windows,
    validate_trading_windows,
    window_name_at,
)
from trading_os.domain.strategy.s01.config import S01Config
from trading_os.domain.strategy.s01.models import SetupStage
from trading_os.domain.strategy.s01.preconditions import blocking_precondition, is_in_killzone
from trading_os.domain.strategy.s02 import S02Config


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def precondition(now: datetime, windows: tuple[TradingWindow, ...] | None = None) -> object:
    kwargs = {} if windows is None else {"windows": windows}
    return blocking_precondition(
        now, releases=[], blackout_minutes=15, lockout_active=False, trades_today=0, max_trades_per_day=15, **kwargs
    )  # type: ignore[arg-type]


class TestWhoOwnsWhichHours:
    def test_s01_keeps_its_historical_windows_and_s02_has_its_own(self) -> None:
        assert [(w.name, w.start, w.end) for w in S01Config().trading_windows] == [
            ("london", time(2, 0), time(5, 0)),
            ("new_york_am", time(7, 0), time(10, 0)),
        ]
        assert [(w.name, w.start, w.end) for w in S02Config().trading_windows] == [
            ("london", time(2, 0), time(5, 0)),
            ("new_york_am", time(8, 30), time(11, 0)),
        ]
        assert S02Config().trading_windows != S01Config().trading_windows
        assert S01Config().trading_windows == S01_TRADING_WINDOWS == DEFAULT_TRADING_WINDOWS  # the historical set, kept
        assert S02Config().trading_windows == S02_TRADING_WINDOWS

    def test_the_london_killzone_is_the_notes_and_the_codes_the_same(self) -> None:
        """The notes (N6) give London as 02:00–05:00 NY; the code already had it. S02 keeps it as it is, S01 too."""
        london = next(w for w in S02_TRADING_WINDOWS if w.name == "london")
        assert (london.start, london.end) == (time(2, 0), time(5, 0))
        assert london in S01_TRADING_WINDOWS

    def test_a_new_account_starts_with_every_hour_a_strategy_may_trade_and_nothing_more(self) -> None:
        assert TradingRules().trading_windows == ACCOUNT_TRADING_WINDOWS
        for window in (*S01_TRADING_WINDOWS, *S02_TRADING_WINDOWS):
            inside = [a for a in ACCOUNT_TRADING_WINDOWS if a.start <= window.start and window.end <= a.end]
            assert inside, f"{window.name} {window.start}–{window.end} is outside the account's envelope"
        assert max(w.end for w in ACCOUNT_TRADING_WINDOWS) == time(11, 0)

    def test_s02_does_not_inherit_the_historical_killzone(self) -> None:
        early = utc(2026, 1, 5, 12, 15)  # 07:15 NY: inside S01's New York window, before S02's
        late = utc(2026, 1, 5, 15, 30)  # 10:30 NY: after S01's, inside S02's
        assert is_in_killzone(early, S01_TRADING_WINDOWS) and not is_in_killzone(early, S02_TRADING_WINDOWS)
        assert not is_in_killzone(late, S01_TRADING_WINDOWS) and is_in_killzone(late, S02_TRADING_WINDOWS)
        assert is_in_killzone(early) and not is_in_killzone(
            late
        )  # with no windows given, S01's (nothing written for S01 changed)


class TestNewYorkTimeAndNothingElse:
    @pytest.mark.parametrize(
        ("label", "winter_utc", "summer_utc"),
        [
            ("08:30 NY opens", (13, 30), (12, 30)),  # EST is UTC−5, EDT is UTC−4
            ("11:00 NY closes (exclusive)", (16, 0), (15, 0)),
        ],
    )
    def test_the_s02_hours_follow_new_york_across_the_dst_change(
        self, label: str, winter_utc: tuple[int, int], summer_utc: tuple[int, int]
    ) -> None:
        opens = label.startswith("08:30")
        for (year, month, day), (hour, minute) in ((((2026, 1, 5)), winter_utc), (((2026, 7, 6)), summer_utc)):
            at = utc(year, month, day, hour, minute)
            before = at - timedelta(minutes=1)
            assert is_in_killzone(at, S02_TRADING_WINDOWS) is opens, (label, at)
            assert is_in_killzone(before, S02_TRADING_WINDOWS) is (not opens), (label, before)

    def test_the_same_wall_clock_in_new_york_is_a_different_utc_hour_either_side_of_the_change(self) -> None:
        # US DST began on 2026-03-08: 08:30 NY is 13:30Z before it and 12:30Z after. Nothing is written in UTC to make it so.
        assert in_trading_window(utc(2026, 3, 6, 13, 30), S02_TRADING_WINDOWS)
        assert not in_trading_window(utc(2026, 3, 6, 12, 30), S02_TRADING_WINDOWS)
        assert in_trading_window(utc(2026, 3, 9, 12, 30), S02_TRADING_WINDOWS)
        assert not in_trading_window(utc(2026, 3, 9, 13, 30) - timedelta(hours=1, minutes=1), S02_TRADING_WINDOWS)
        # and the autumn change (2026-11-01)
        assert in_trading_window(utc(2026, 10, 30, 12, 30), S02_TRADING_WINDOWS)  # still EDT: 08:30
        assert in_trading_window(utc(2026, 11, 2, 13, 30), S02_TRADING_WINDOWS)  # EST: 08:30
        assert not in_trading_window(utc(2026, 11, 2, 12, 30), S02_TRADING_WINDOWS)  # 07:30 EST

    def test_an_instant_is_read_the_same_whatever_zone_it_is_written_in(self) -> None:
        """The MT5 server's clock (here UTC+3) and UTC name the same instant; only New York decides whether it is in a window."""
        server = timezone(timedelta(hours=3))
        instant_utc = utc(2026, 1, 5, 13, 30)  # 08:30 NY
        instant_server = instant_utc.astimezone(
            server
        )  # 16:30 on the server's clock — inside no New York window by its digits
        assert instant_server.hour == 16
        assert (
            is_in_killzone(instant_server, S02_TRADING_WINDOWS)
            is is_in_killzone(instant_utc, S02_TRADING_WINDOWS)
            is True
        )
        assert window_name_at(instant_server, S02_TRADING_WINDOWS) == "new_york_am"

    def test_a_weekend_is_never_open_for_the_gate(self) -> None:
        assert not in_trading_window(utc(2026, 1, 3, 14, 0), S02_TRADING_WINDOWS)  # Saturday 09:00 NY
        assert minutes_until_window_end(utc(2026, 1, 5, 15, 30), S02_TRADING_WINDOWS) == pytest.approx(
            30
        )  # 10:30 → 11:00


class TestThePreconditionUsesTheStrategysOwnWindows:
    def test_s01_is_unchanged(self) -> None:
        assert precondition(utc(2026, 1, 5, 12, 15)) is None  # 07:15 NY
        blocked = precondition(utc(2026, 1, 5, 15, 30))  # 10:30 NY
        assert blocked is not None and blocked.stage is SetupStage.PRECONDITION_SESSION_WINDOW  # type: ignore[attr-defined]

    def test_s02_opens_at_half_past_eight_and_closes_at_eleven(self) -> None:
        for at, open_ in (
            (utc(2026, 1, 5, 12, 15), False),  # 07:15 NY — S01's, not S02's
            (utc(2026, 1, 5, 13, 29), False),  # 08:29
            (utc(2026, 1, 5, 13, 30), True),  # 08:30
            (utc(2026, 1, 5, 15, 59), True),  # 10:59
            (utc(2026, 1, 5, 16, 0), False),  # 11:00
            (utc(2026, 1, 5, 8, 0), True),  # 03:00 NY — the London killzone
        ):
            blocked = precondition(at, S02_TRADING_WINDOWS)
            assert (blocked is None) is open_, at

    def test_the_refusal_says_which_hours_were_in_force(self) -> None:
        blocked = precondition(utc(2026, 1, 5, 12, 15), S02_TRADING_WINDOWS)
        assert blocked is not None
        assert blocked.detail == (  # type: ignore[attr-defined]
            "outside the strategy's trading windows (NY time): london 02:00–05:00, new_york_am 08:30–11:00"
        )


class TestWindowsAreConfigurable:
    def test_they_are_read_from_text_in_new_york_time(self) -> None:
        windows = parse_trading_windows("london=02:00-05:00, new_york_am=08:30-11:00")
        assert windows == S02_TRADING_WINDOWS
        assert describe_trading_windows(windows) == "london 02:00–05:00, new_york_am 08:30–11:00"
        assert S02Config(trading_windows=parse_trading_windows("new_york_am=09:00-10:30")).trading_windows[
            0
        ].start == time(9, 0)

    @pytest.mark.parametrize(
        "text",
        [
            "",  # no window at all is not « every hour », it is a mistake
            "london",
            "london=02:00",
            "london=2am-5am",
            "london=05:00-02:00",  # ends before it starts (a window that crosses midnight is not supported: write two)
            "london=02:00-05:00,london=06:00-07:00",  # a name twice
            "a=02:00-05:00,b=04:00-06:00",  # overlapping
            "london=02:00-02:00",
        ],
    )
    def test_anything_malformed_is_refused_never_guessed(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_trading_windows(text)

    def test_the_settings_refuse_a_malformed_value_and_keep_the_defaults_when_empty(self) -> None:
        assert Settings(_env_file=None).strategy_s02_windows == ""  # empty = the strategy's own defaults
        assert Settings(_env_file=None, strategy_s02_windows="new_york_am=08:30-11:00").strategy_s02_windows
        with pytest.raises(ValidationError):
            Settings(_env_file=None, strategy_s01_windows="london=05:00-02:00")

    def test_a_window_set_can_be_checked_as_it_stands(self) -> None:
        assert validate_trading_windows(S02_TRADING_WINDOWS) == S02_TRADING_WINDOWS
        with pytest.raises(ValueError):
            validate_trading_windows(())
