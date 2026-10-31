"""The FRED client against a simulated server: dates become UTC instants with the right EST/EDT offset, only future ones are
kept — and no failure mode ever leaks the API key (it travels in the URL)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from trading_os.domain.market.calendar import FRED_WHITELIST, FredReleaseSpec
from trading_os.infrastructure.news.fred import FRED_RELEASE_DATES_URL, FredCalendarClient, FredError

KEY = "SECRET-FRED-KEY-0123456789abcdef"
CPI = FRED_WHITELIST[0]
FOMC = next(s for s in FRED_WHITELIST if s.label == "FOMC")
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def client_for(handler: httpx.MockTransport) -> FredCalendarClient:
    return FredCalendarClient(SecretStr(KEY), http=httpx.AsyncClient(transport=handler))


def answer(*dates: str) -> httpx.MockTransport:
    body = {"release_dates": [{"release_id": 10, "date": d} for d in dates]}
    return httpx.MockTransport(lambda request: httpx.Response(200, json=body))


async def test_dates_become_utc_instants_future_only_soonest_first() -> None:
    client = client_for(answer("2026-12-10", "2026-09-10", "2026-10-14", "2026-11-12"))
    instants = await client.fetch_upcoming(CPI, NOW)
    # 08:30 US Eastern: EDT (UTC-4) on 2026-10-14, EST (UTC-5) from 2026-11-01 — the offset of *that* date, not a constant.
    assert instants == [
        datetime(2026, 10, 14, 12, 30, tzinfo=UTC),
        datetime(2026, 11, 12, 13, 30, tzinfo=UTC),
        datetime(2026, 12, 10, 13, 30, tzinfo=UTC),
    ]


async def test_fomc_uses_its_own_time_of_day() -> None:
    instants = await client_for(answer("2026-12-09")).fetch_upcoming(FOMC, NOW)
    assert instants == [datetime(2026, 12, 9, 19, 0, tzinfo=UTC)]  # 14:00 EST


async def test_a_release_with_nothing_scheduled_is_an_empty_list_not_an_error() -> None:
    assert await client_for(answer()).fetch_upcoming(CPI, NOW) == []


async def test_the_request_names_the_release_and_carries_the_key_as_a_query_parameter() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"release_dates": []})

    await client_for(httpx.MockTransport(handler)).fetch_upcoming(CPI, NOW)
    request = seen[0]
    assert str(request.url).startswith(FRED_RELEASE_DATES_URL)
    assert request.url.params["release_id"] == "10" and request.url.params["file_type"] == "json"
    assert request.url.params["api_key"] == KEY and request.method == "GET"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            400,
            json={"error_code": 400, "error_message": "Bad Request. The value for variable api_key is not registered."},
        ),
        httpx.Response(429),
        httpx.Response(503, text="down"),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"error_code": 500}),
        httpx.Response(200, json={"release_dates": [{"release_id": 10, "date": "soon"}]}),
        httpx.Response(200, json={"release_dates": [{"release_id": 10}]}),
        httpx.Response(200, json=[1, 2, 3]),
    ],
)
async def test_every_failure_raises_a_fred_error_that_never_contains_the_key(response: httpx.Response) -> None:
    client = client_for(httpx.MockTransport(lambda request: response))
    with pytest.raises(FredError) as caught:
        await client.fetch_upcoming(CPI, NOW)
    text = f"{caught.value!s} {caught.value.safe_message} {caught.value.__cause__!r} {caught.value.__context__!r}"
    assert KEY not in text and "api_key" not in text.lower() and caught.value.code == "fred_unavailable"


async def test_a_network_failure_is_a_fred_error_without_the_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(FredError) as caught:
        await client_for(httpx.MockTransport(handler)).fetch_upcoming(CPI, NOW)
    assert "ConnectError" in str(caught.value) and KEY not in str(caught.value) and caught.value.__cause__ is None


async def test_the_error_names_the_release_so_the_log_says_which_one_failed() -> None:
    client = client_for(httpx.MockTransport(lambda request: httpx.Response(500)))
    spec = FredReleaseSpec(release_id=54, label="PCE US", hour_et=8, minute_et=30)
    with pytest.raises(FredError, match="release 54"):
        await client.fetch_upcoming(spec, NOW)
