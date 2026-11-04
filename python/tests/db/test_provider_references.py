"""The provider's loss references against a real PostgreSQL: written once, never rewritten, isolated by account (ADR 0036)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from trading_os.domain.providers.loss_floors import LossReference
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.database.repositories import Repositories

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repos(db: Database) -> Repositories:
    return Repositories.create(db)


def reference(day: date, balance: float, *, source: str = "observed") -> LossReference:
    return LossReference(
        local_date=day,
        timezone="Europe/Prague",
        reference_balance=balance,
        recorded_at=NOW,
        source=source,  # type: ignore[arg-type]
        rule_set_id="FTMO_ACCOUNT_2STEP@2026-11-02",
    )


async def test_the_first_reference_written_for_a_day_is_the_one_that_stays(repos: Repositories) -> None:
    first = reference(date(2026, 11, 3), 100_000.0)
    assert await repos.providers.record("acct", first) is True
    rewrite = reference(date(2026, 11, 3), 90_000.0, source="reconstructed")
    assert (
        await repos.providers.record("acct", rewrite) is False
    )  # a restart, a reconnection, a settings change: nothing moves
    assert await repos.providers.get("acct", date(2026, 11, 3)) == first


async def test_references_round_trip_whole_and_come_back_in_date_order(repos: Repositories) -> None:
    refs = [reference(date(2026, 11, day), 100_000.0 + day) for day in (5, 3, 4)]
    assert await repos.providers.record_many("acct", refs) == 3
    stored = await repos.providers.all("acct")
    assert [item.local_date for item in stored] == [date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)]
    assert stored[0] == reference(date(2026, 11, 3), 100_003.0)
    assert stored[0].source == "observed" and stored[0].timezone == "Europe/Prague"


async def test_recording_many_counts_only_what_was_new(repos: Repositories) -> None:
    await repos.providers.record("acct", reference(date(2026, 11, 3), 1.0))
    written = await repos.providers.record_many(
        "acct", [reference(date(2026, 11, 3), 2.0), reference(date(2026, 11, 4), 3.0)]
    )
    assert written == 1
    assert (await repos.providers.get("acct", date(2026, 11, 3))).reference_balance == 1.0  # type: ignore[union-attr]


async def test_each_account_has_its_own_references(repos: Repositories) -> None:
    await repos.providers.record("demo", reference(date(2026, 11, 3), 10_000.0))
    await repos.providers.record("real", reference(date(2026, 11, 3), 50_000.0))
    assert (await repos.providers.get("demo", date(2026, 11, 3))).reference_balance == 10_000.0  # type: ignore[union-attr]
    assert (await repos.providers.get("real", date(2026, 11, 3))).reference_balance == 50_000.0  # type: ignore[union-attr]
    assert await repos.providers.get("other", date(2026, 11, 3)) is None
    assert await repos.providers.all("other") == []


async def test_a_reference_of_a_day_nobody_recorded_is_absent_not_zero(repos: Repositories) -> None:
    assert await repos.providers.get("acct", date(2026, 1, 1)) is None


async def test_the_source_is_constrained_to_what_a_reference_can_be(db: Database) -> None:
    with pytest.raises(Exception, match="source"):
        await db.execute(
            "INSERT INTO provider_loss_references "
            "(account_id, local_date, timezone, reference_balance, recorded_at, source, rule_set_id) "
            "VALUES ('a', '2026-11-03', 'UTC', 1, now(), 'guessed', 'x')"
        )
