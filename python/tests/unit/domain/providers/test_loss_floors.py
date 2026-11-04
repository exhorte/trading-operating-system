"""The provider's loss floors: reference balance at 00:00 CE(S)T, equity tested, trailing maximum, and a safe refusal whenever a
reference is missing, stale or incomplete. Simulated accounts; the arithmetic is what is proven here, not a provider's server."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from trading_os.domain.providers.loss_floors import (
    DAILY_LOSS_BREACHED,
    DAILY_REFERENCE_MISSING,
    DAILY_REFERENCE_STALE,
    EQUITY_UNKNOWN,
    INITIAL_CAPITAL_MISSING,
    MAX_LOSS_BREACHED,
    MAX_METHOD_UNSUPPORTED,
    MAX_REFERENCE_INCOMPLETE,
    CashFlow,
    LossReference,
    ProviderLossState,
    balance_at,
    day_start_utc,
    evaluate_loss_state,
    local_day,
    missing_days,
    reference_from_flows,
    remaining_percent,
)
from trading_os.domain.providers.rules import ProviderProduct, rule_set_for

PRAGUE = "Europe/Prague"
NOON = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)  # 13:00 in Prague (CET, UTC+1)
TODAY = date(2026, 11, 3)


def reference(day: date, balance: float) -> LossReference:
    return LossReference(
        local_date=day,
        timezone=PRAGUE,
        reference_balance=balance,
        recorded_at=day_start_utc(day, PRAGUE),
        source="observed",
        rule_set_id="test",
    )


def rules(product: ProviderProduct):
    found = rule_set_for(product)
    assert found is not None
    return found


def state(
    product: ProviderProduct,
    *,
    equity: float,
    daily: LossReference | None,
    refs: list[LossReference] | None = None,
    complete: bool = True,
    now: datetime = NOON,
    capital: float = 100_000.0,
) -> ProviderLossState:
    return evaluate_loss_state(
        rules(product),
        initial_capital=capital,
        equity=equity,
        now=now,
        daily_reference=daily,
        references=refs or [],
        references_complete=complete,
    )


class TestTheDayStartsAtMidnightInCentralEuropeanTime:
    def test_winter_and_summer_midnight_in_utc(self) -> None:
        assert day_start_utc(date(2026, 11, 3), PRAGUE) == datetime(2026, 11, 2, 23, 0, tzinfo=UTC)  # CET = UTC+1
        assert day_start_utc(date(2026, 7, 16), PRAGUE) == datetime(2026, 7, 15, 22, 0, tzinfo=UTC)  # CEST = UTC+2

    def test_the_local_day_turns_over_at_that_instant_and_not_at_utc_midnight(self) -> None:
        assert local_day(datetime(2026, 11, 3, 22, 59, tzinfo=UTC), PRAGUE) == date(2026, 11, 3)
        assert local_day(datetime(2026, 11, 3, 23, 0, tzinfo=UTC), PRAGUE) == date(2026, 11, 4)
        assert local_day(datetime(2026, 11, 3, 23, 30, tzinfo=UTC), "UTC") == date(2026, 11, 3)

    def test_it_is_not_the_brokers_server_midnight(self) -> None:
        # A MetaTrader server at GMT+2 turns its day at 22:00 UTC in winter: an hour before CET midnight. The provider's day is
        # the named zone's, so the two readings differ — which is why the zone is data and not the measured server offset.
        server_midnight_utc = datetime(2026, 11, 2, 22, 0, tzinfo=UTC)
        assert day_start_utc(TODAY, PRAGUE) != server_midnight_utc

    def test_a_reference_of_yesterday_is_stale_the_minute_the_day_turns(self) -> None:
        yesterday = reference(date(2026, 11, 3), 100_000)
        just_after = datetime(2026, 11, 3, 23, 0, tzinfo=UTC)
        result = state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=100_000, daily=yesterday, now=just_after)
        assert result.status == "unknown" and DAILY_REFERENCE_STALE in result.reasons


class TestDailyFloor:
    def test_the_floor_is_the_midnight_balance_minus_the_daily_amount_and_equity_is_tested(self) -> None:
        daily = reference(TODAY, 100_000)
        result = state(ProviderProduct.FTMO_CHALLENGE_1STEP, equity=98_500, daily=daily, refs=[daily])
        assert (result.daily_loss_amount, result.daily_floor, result.daily_remaining) == (3_000.0, 97_000.0, 1_500.0)
        assert result.status == "ok" and result.timezone == PRAGUE and result.rule_version == "2026-11-02"

    def test_a_better_midnight_balance_raises_the_floor_of_that_day(self) -> None:
        result = state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=104_000, daily=reference(TODAY, 104_000))
        assert result.daily_floor == 99_000.0  # 104 000 − 5 % of the initial 100 000

    def test_the_floor_is_a_function_of_the_reference_not_of_the_current_balance(self) -> None:
        # The same equity against the same reference gives the same floor however many times it is evaluated.
        daily = reference(TODAY, 100_000)
        first = state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=97_000, daily=daily)
        second = state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=97_000, daily=daily)
        assert first == second and first.daily_floor == 95_000.0

    def test_reaching_the_floor_exactly_is_a_breach(self) -> None:
        result = state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=95_000, daily=reference(TODAY, 100_000))
        assert result.status == "breached" and DAILY_LOSS_BREACHED in result.reasons and result.blocks_entries

    def test_floating_loss_counts_because_equity_is_what_is_tested(self) -> None:
        # Balance still 100 000, but a floating loss took the equity to 94 900: the floor of 95 000 is broken.
        result = state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=94_900, daily=reference(TODAY, 100_000))
        assert result.status == "breached"


class TestMaximumFloor:
    def test_static_two_step_never_moves(self) -> None:
        refs = [reference(date(2026, 10, 30), 110_000), reference(TODAY, 120_000)]
        result = state(ProviderProduct.FTMO_ACCOUNT_2STEP, equity=118_000, daily=refs[-1], refs=refs)
        assert (result.max_reference_balance, result.max_floor) == (100_000.0, 90_000.0)

    def test_one_step_trails_the_highest_midnight_balance(self) -> None:
        refs = [reference(date(2026, 11, 1), 102_000), reference(date(2026, 11, 2), 105_000), reference(TODAY, 103_000)]
        result = state(ProviderProduct.FTMO_ACCOUNT_1STEP, equity=103_000, daily=refs[-1], refs=refs)
        assert (result.max_reference_balance, result.max_floor, result.max_remaining) == (105_000.0, 95_000.0, 8_000.0)

    def test_the_initial_capital_is_the_reference_while_nothing_exceeds_it(self) -> None:
        refs = [reference(TODAY, 99_000)]
        result = state(ProviderProduct.FTMO_CHALLENGE_1STEP, equity=99_000, daily=refs[0], refs=refs)
        assert (result.max_reference_balance, result.max_floor) == (100_000.0, 90_000.0)

    def test_the_trailing_floor_only_rises(self) -> None:
        low = [reference(date(2026, 11, 2), 105_000), reference(TODAY, 101_000)]
        result = state(ProviderProduct.FTMO_ACCOUNT_1STEP, equity=101_000, daily=low[-1], refs=low)
        assert result.max_reference_balance == 105_000.0  # a lower midnight balance never lowers it

    def test_the_trailing_maximum_breaches_with_the_daily_limit_when_equity_meets_both_floors(self) -> None:
        refs = [reference(date(2026, 11, 2), 110_000), reference(TODAY, 110_000)]
        result = state(ProviderProduct.FTMO_ACCOUNT_1STEP, equity=100_000, daily=refs[-1], refs=refs)
        # daily floor 107 000 and maximum floor 100 000 (equity == floor) are both broken
        assert result.status == "breached" and {DAILY_LOSS_BREACHED, MAX_LOSS_BREACHED} <= set(result.reasons)

    def test_an_incomplete_history_makes_the_trailing_maximum_unknown_not_a_guess(self) -> None:
        daily = reference(TODAY, 100_000)
        result = state(ProviderProduct.FTMO_ACCOUNT_1STEP, equity=100_000, daily=daily, refs=[daily], complete=False)
        assert result.status == "unknown" and MAX_REFERENCE_INCOMPLETE in result.reasons
        assert result.max_floor is None and result.blocks_entries
        assert result.daily_floor == 97_000.0  # what is known stays known

    def test_the_static_maximum_does_not_need_the_history(self) -> None:
        daily = reference(TODAY, 100_000)
        result = state(ProviderProduct.FTMO_ACCOUNT_2STEP, equity=100_000, daily=daily, refs=[daily], complete=False)
        assert result.status == "ok"

    def test_the_intraday_trailing_maximum_is_not_tracked_so_it_is_refused(self) -> None:
        daily = reference(TODAY, 100_000)
        result = state(ProviderProduct.FTMO_INSTANT, equity=100_000, daily=daily, refs=[daily])
        assert result.status == "unknown" and MAX_METHOD_UNSUPPORTED in result.reasons


class TestMissingInformationBlocksEntries:
    def test_no_daily_reference(self) -> None:
        result = state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=100_000, daily=None)
        assert result.status == "unknown" and DAILY_REFERENCE_MISSING in result.reasons and result.blocks_entries
        assert result.daily_floor is None

    def test_no_initial_capital(self) -> None:
        result = evaluate_loss_state(
            rules(ProviderProduct.FTMO_CHALLENGE_2STEP),
            initial_capital=None,
            equity=100_000,
            now=NOON,
            daily_reference=reference(TODAY, 100_000),
        )
        assert result.status == "unknown" and result.reasons == (INITIAL_CAPITAL_MISSING,)

    def test_no_equity(self) -> None:
        result = evaluate_loss_state(
            rules(ProviderProduct.FTMO_CHALLENGE_2STEP),
            initial_capital=100_000,
            equity=None,
            now=NOON,
            daily_reference=reference(TODAY, 100_000),
        )
        assert result.status == "unknown" and result.reasons == (EQUITY_UNKNOWN,)

    def test_a_product_without_a_provider_floor_has_nothing_to_enforce(self) -> None:
        for found in (rule_set_for(ProviderProduct.EXNESS_STANDARD), None):
            result = evaluate_loss_state(found, initial_capital=None, equity=None, now=NOON, daily_reference=None)
            assert result.status == "not_applicable" and not result.blocks_entries


class TestAccountingIsCarried:
    def test_the_components_of_the_equity_are_kept_as_given(self) -> None:
        result = evaluate_loss_state(
            rules(ProviderProduct.FTMO_CHALLENGE_2STEP),
            initial_capital=100_000,
            equity=99_000,
            now=NOON,
            daily_reference=reference(TODAY, 100_000),
            floating_pl=-1_200.0,
            realized_pl=300.0,
            commissions=-40.0,
            swaps=-60.0,
        )
        assert (result.floating_pl, result.realized_pl, result.commissions, result.swaps) == (
            -1_200.0,
            300.0,
            -40.0,
            -60.0,
        )

    def test_what_the_caller_did_not_know_stays_none_never_zero(self) -> None:
        result = state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=99_000, daily=reference(TODAY, 100_000))
        assert (result.floating_pl, result.realized_pl, result.commissions, result.swaps) == (None, None, None, None)


class TestRebuildingAReferenceAfterARestart:
    def test_a_balance_is_rebuilt_from_what_moved_it_since(self) -> None:
        midnight = day_start_utc(TODAY, PRAGUE)
        flows = [
            CashFlow(at=datetime(2026, 11, 3, 7, 0, tzinfo=UTC), amount=-120.0),  # a loss realised this morning
            CashFlow(at=datetime(2026, 11, 3, 9, 0, tzinfo=UTC), amount=350.5),  # a win
            CashFlow(
                at=datetime(2026, 11, 2, 15, 0, tzinfo=UTC), amount=999.0
            ),  # before midnight: already in the balance
        ]
        assert balance_at(midnight, 100_230.5, flows) == 100_000.0

    def test_a_deposit_after_midnight_does_not_raise_the_reference(self) -> None:
        midnight = day_start_utc(TODAY, PRAGUE)
        deposit = CashFlow(at=datetime(2026, 11, 3, 10, 0, tzinfo=UTC), amount=5_000.0)
        assert balance_at(midnight, 105_000.0, [deposit]) == 100_000.0

    def test_a_position_open_across_midnight_does_not_matter_to_a_balance(self) -> None:
        # Only closed deals move the balance: no flow, so the balance then is the balance now.
        assert balance_at(day_start_utc(TODAY, PRAGUE), 100_000.0, []) == 100_000.0

    def test_the_rebuilt_reference_says_it_was_rebuilt(self) -> None:
        ref = reference_from_flows(
            TODAY,
            timezone=PRAGUE,
            current_balance=100_300.0,
            flows=[CashFlow(at=NOON, amount=300.0)],
            recorded_at=NOON,
            rule_set_id="x",
        )
        assert (ref.reference_balance, ref.source, ref.local_date) == (100_000.0, "reconstructed", TODAY)


class TestUnits:
    def test_the_room_left_is_expressed_in_percent_of_the_initial_capital(self) -> None:
        daily = reference(TODAY, 100_000)
        result = state(ProviderProduct.FTMO_CHALLENGE_1STEP, equity=98_500, daily=daily, refs=[daily])
        assert remaining_percent(result, "daily") == pytest.approx(1.5)
        assert remaining_percent(result, "max") == pytest.approx(8.5)

    def test_unknown_room_is_none(self) -> None:
        assert remaining_percent(state(ProviderProduct.FTMO_CHALLENGE_2STEP, equity=1, daily=None), "daily") is None

    def test_the_days_a_history_lacks(self) -> None:
        refs = [reference(date(2026, 11, 1), 1.0), reference(date(2026, 11, 3), 1.0)]
        assert missing_days(refs, date(2026, 11, 1), date(2026, 11, 3)) == [date(2026, 11, 2)]
