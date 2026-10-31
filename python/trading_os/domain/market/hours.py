"""When a market is open — needed to tell « no tick because the market is closed » from « no tick because the feed died ».

Retail FX and metals trade from Sunday 17:00 to Friday 17:00 New York time (DST-aware through the zone), crypto never
closes. A stale quote on a closed market is normal and must not raise an alarm, nor must it block anything the
trader could do anyway; a stale quote on an open one is a degraded system.
"""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.market.sessions import NY_TIME_ZONE

ALWAYS_OPEN = frozenset({"BTCUSD", "ETHUSD"})
_FRIDAY, _SATURDAY, _SUNDAY = 4, 5, 6
_WEEK_BOUNDARY_HOUR = 17  # New York local time


def is_market_open(canonical_symbol: str | None, ts: datetime) -> bool:
    if canonical_symbol in ALWAYS_OPEN:
        return True
    local = ts.astimezone(NY_TIME_ZONE)
    weekday, hour = local.weekday(), local.hour
    if weekday == _SATURDAY:
        return False
    if weekday == _FRIDAY and hour >= _WEEK_BOUNDARY_HOUR:
        return False
    return not (weekday == _SUNDAY and hour < _WEEK_BOUNDARY_HOUR)
