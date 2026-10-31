"""Thin client for FRED's ``fred/release/dates`` endpoint (https://fred.stlouisfed.org/docs/api/fred/release_dates.html).

Fetches one whitelisted release, keeps the dates still to come and resolves each to a UTC instant (``domain/market/calendar``:
FRED gives a *date* only, the publication time of day is the release's long-standing convention). Read-only; it reports
FRED's schedule and decides nothing. Raises on any failure — the caller decides what that means (the news service never
wipes its cache because FRED is down).

**The API key travels in the query string** — FRED accepts no other way — and an ``httpx`` error message quotes the URL. So
every error raised from here is rebuilt from the status code alone: the key can reach neither a log nor an API response.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx
from pydantic import SecretStr

from trading_os.domain.market.calendar import FredReleaseSpec, release_utc_instant
from trading_os.shared.errors import Unavailable

FRED_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"


class FredError(Unavailable):
    """FRED could not be read. The message never contains the URL (and so never the key)."""

    code = "fred_unavailable"


class FredCalendarClient:
    def __init__(self, api_key: SecretStr, *, http: httpx.AsyncClient | None = None, timeout_s: float = 15.0) -> None:
        self._key = api_key
        self._http = http or httpx.AsyncClient(timeout=timeout_s)
        self._owns_http = http is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def fetch_upcoming(self, spec: FredReleaseSpec, now: datetime) -> list[datetime]:
        """Every UTC instant FRED has scheduled for this release at or after ``now``, soonest first."""
        params: dict[str, str | int] = {
            "release_id": spec.release_id,
            "include_release_dates_with_no_data": "true",
            "sort_order": "asc",
            "file_type": "json",
            "api_key": self._key.get_secret_value(),
        }
        failure: str | None = None
        body: Any = None
        try:
            response = await self._http.get(FRED_RELEASE_DATES_URL, params=params)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as error:
            failure = f"FRED answered HTTP {error.response.status_code} for release {spec.release_id}"
        except httpx.HTTPError as error:
            failure = f"FRED could not be reached for release {spec.release_id} ({type(error).__name__})"
        except ValueError:
            failure = f"FRED sent an unreadable answer for release {spec.release_id}"
        if failure is not None:
            # Raised *outside* the handlers: an exception raised inside one keeps the original as ``__context__``, and
            # the original quotes the URL — key included. Nothing of it may stay attached.
            raise FredError(failure)
        return self._instants(body, spec, now)

    @staticmethod
    def _instants(body: Any, spec: FredReleaseSpec, now: datetime) -> list[datetime]:
        rows = body.get("release_dates") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise FredError(f"FRED's answer for release {spec.release_id} has no release_dates")
        instants: list[datetime] = []
        for row in rows:
            day = _parse_day(row)
            if day is None:
                raise FredError(f"FRED sent a date that cannot be read for release {spec.release_id}")
            instants.append(release_utc_instant(day, spec.hour_et, spec.minute_et))
        return sorted(instant for instant in instants if instant >= now)


def _parse_day(row: Any) -> date | None:
    try:
        return date.fromisoformat(str(row["date"]))
    except (KeyError, TypeError, ValueError):
        return None
