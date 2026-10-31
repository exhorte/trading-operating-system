"""Market domain: sessions (UTC buckets + DST-aware New York windows), the FRED calendar, symbol names."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from trading_os.domain.market.calendar import (
    FRED_WHITELIST,
    CalendarSnapshot,
    UpcomingRelease,
    is_news_blackout,
    next_release,
    release_utc_instant,
)
from trading_os.domain.market.models import Tick
from trading_os.domain.market.sessions import (
    in_trading_window,
    past_ny_lunch,
    session_enabled,
    session_for_timestamp,
    window_name_at,
)
from trading_os.domain.market.symbols import to_broker, to_canonical
from trading_os.domain.primitives import TradingSession


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class TestUtcSessionBuckets:
    def test_buckets(self) -> None:
        assert session_for_timestamp(utc(2026, 1, 5, 8, 0)) is TradingSession.LONDON
        assert session_for_timestamp(utc(2026, 1, 5, 13, 0)) is TradingSession.NEW_YORK_AM
        assert session_for_timestamp(utc(2026, 1, 5, 17, 0)) is TradingSession.NEW_YORK_PM
        assert session_for_timestamp(utc(2026, 1, 5, 21, 0)) is TradingSession.OFF_SESSION

    def test_asia_wraps_midnight(self) -> None:
        assert session_for_timestamp(utc(2026, 1, 5, 23, 30)) is TradingSession.ASIA
        assert session_for_timestamp(utc(2026, 1, 5, 3, 0)) is TradingSession.ASIA

    def test_enabled_flags(self) -> None:
        assert session_enabled(TradingSession.LONDON) and not session_enabled(TradingSession.ASIA)


class TestNewYorkTradingWindows:
    """The user's killzones: London 02:00–05:00 and New York AM 07:00–10:00, New York local time (S01)."""

    def test_winter_est_is_utc_minus_5(self) -> None:
        assert in_trading_window(utc(2026, 1, 5, 12, 0))  # 07:00 NY
        assert not in_trading_window(utc(2026, 1, 5, 11, 59))  # 06:59 NY
        assert in_trading_window(utc(2026, 1, 5, 7, 0))  # 02:00 NY (London killzone)
        assert not in_trading_window(utc(2026, 1, 5, 10, 0))  # 05:00 NY: end is exclusive
        assert not in_trading_window(utc(2026, 1, 5, 15, 0))  # 10:00 NY: end is exclusive

    def test_summer_edt_is_utc_minus_4(self) -> None:
        assert in_trading_window(utc(2026, 7, 6, 11, 0))  # 07:00 NY
        assert not in_trading_window(utc(2026, 7, 6, 10, 59))
        assert in_trading_window(utc(2026, 7, 6, 6, 0))  # 02:00 NY

    def test_the_window_follows_new_york_across_the_dst_change(self) -> None:
        # US DST began on 2026-03-08. The same wall-clock 07:00 NY is 12:00Z before and 11:00Z after.
        assert in_trading_window(utc(2026, 3, 6, 12, 0)) and not in_trading_window(utc(2026, 3, 6, 11, 0))
        assert in_trading_window(utc(2026, 3, 9, 11, 0)) and not in_trading_window(utc(2026, 3, 9, 10, 59))

    def test_weekends_are_never_open(self) -> None:
        # The old gate counted a Saturday « killzone » as open (audit TD-08).
        assert not in_trading_window(utc(2026, 1, 3, 12, 0))  # Saturday 07:00 NY
        assert not in_trading_window(utc(2026, 1, 4, 12, 0))  # Sunday

    def test_window_name(self) -> None:
        assert window_name_at(utc(2026, 1, 5, 12, 30)) == "new_york_am"
        assert window_name_at(utc(2026, 1, 5, 7, 30)) == "london"
        assert window_name_at(utc(2026, 1, 5, 20, 0)) is None

    def test_no_new_position_after_new_york_lunch(self) -> None:
        assert past_ny_lunch(utc(2026, 1, 5, 17, 0)) and not past_ny_lunch(utc(2026, 1, 5, 16, 59))
        assert past_ny_lunch(utc(2026, 7, 6, 16, 0)) and not past_ny_lunch(utc(2026, 7, 6, 15, 59))


class TestFredCalendar:
    def test_est_in_winter_verified_against_a_real_fomc_release(self) -> None:
        # « For release at 2:00 p.m. EST December 10, 2025 » — federalreserve.gov
        assert release_utc_instant(date(2025, 12, 10), 14, 0) == utc(2025, 12, 10, 19, 0)

    def test_edt_in_summer(self) -> None:
        assert release_utc_instant(date(2026, 7, 14), 8, 30) == utc(2026, 7, 14, 12, 30)

    def test_whitelist_has_no_ism_and_the_verified_release_ids(self) -> None:
        assert sorted(spec.release_id for spec in FRED_WHITELIST) == [9, 10, 50, 54, 101]

    cpi = UpcomingRelease(release_id=10, label="CPI US", scheduled_at=utc(2026, 9, 5, 14, 0))
    fomc = UpcomingRelease(release_id=101, label="FOMC", scheduled_at=utc(2026, 9, 17, 18, 0))
    past = UpcomingRelease(release_id=9, label="Retail Sales US", scheduled_at=utc(2026, 9, 1, 12, 30))

    def test_blackout_is_symmetric_and_inclusive(self) -> None:
        now = utc(2026, 9, 5, 13, 30)
        assert is_news_blackout(now, [self.cpi], 30)  # exactly 30 min away
        assert is_news_blackout(utc(2026, 9, 5, 14, 15), [self.cpi], 30)  # 15 min after
        assert not is_news_blackout(utc(2026, 9, 5, 14, 31), [self.cpi], 30)
        assert not is_news_blackout(utc(2026, 9, 5, 13, 0), [self.cpi, self.fomc], 30)
        assert not is_news_blackout(now, [], 30)

    def test_next_release(self) -> None:
        now = utc(2026, 9, 5, 13, 30)
        assert next_release(now, [self.fomc, self.past, self.cpi]) == self.cpi
        assert next_release(now, []) is None and next_release(now, [self.past]) is None

    def test_a_stale_or_never_synced_calendar_is_unknown_not_empty(self) -> None:
        now = utc(2026, 9, 5, 13, 30)
        max_age = timedelta(hours=48)
        assert CalendarSnapshot(releases=None).usable(now, max_age) is None  # never synced
        assert CalendarSnapshot(releases=[self.cpi], synced_at=now - timedelta(hours=49)).usable(now, max_age) is None
        assert CalendarSnapshot(releases=[], synced_at=now - timedelta(hours=1)).usable(now, max_age) == []
        assert CalendarSnapshot(releases=[self.cpi], synced_at=now - timedelta(hours=1)).usable(now, max_age) == [
            self.cpi
        ]


class TestSymbolsAndTicks:
    def test_canonical_and_broker_names(self) -> None:
        assert to_canonical("EURUSDm") == "EURUSD" and to_canonical("XAUUSD") == "XAUUSD"
        assert to_canonical("NOPEm") is None and to_canonical("") is None
        assert to_broker("EURUSD", "m") == "EURUSDm" and to_broker("EURUSD") == "EURUSD"

    def test_tick_spread_and_mid(self) -> None:
        tick = Tick(symbol="EURUSDm", bid=1.10000, ask=1.10008, time=utc(2026, 1, 5, 10, 0))
        assert tick.spread == 0.00008 and tick.mid == 1.10004
