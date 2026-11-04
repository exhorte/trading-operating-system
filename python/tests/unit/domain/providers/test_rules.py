"""Provider rule sets: what each product's contract says, where it came from, and what is deliberately not claimed."""

from __future__ import annotations

from datetime import date

import pytest

from trading_os.domain.accounts.models import FtmoChallenge, Provider
from trading_os.domain.providers.rules import (
    RULE_SETS,
    LossMethod,
    ProviderProduct,
    ftmo_product_of,
    products_of,
    rule_set_by_id,
    rule_set_for,
)


def ftmo(type_: str, phase: str, variant: str = "standard") -> FtmoChallenge:
    return FtmoChallenge.model_validate({"type": type_, "accountSize": 100_000, "phase": phase, "variant": variant})


class TestEveryRuleSetCarriesItsProvenance:
    @pytest.mark.parametrize("rule_set", RULE_SETS, ids=lambda r: r.rule_set_id)
    def test_a_rule_set_has_an_id_a_version_and_sources(self, rule_set) -> None:
        assert rule_set.rule_set_id == f"{rule_set.product.value}@{rule_set.version}"
        assert rule_set.sources, "a rule without a source is a guess"
        assert all(source.url.startswith("https://") and source.retrieved_on for source in rule_set.sources)

    def test_the_exness_page_we_could_not_read_says_so(self) -> None:
        exness = rule_set_for(ProviderProduct.EXNESS_STANDARD)
        assert exness is not None
        assert [source.read_how for source in exness.sources] == ["search_summary"]

    def test_the_registry_resolves_ids_and_products(self) -> None:
        assert rule_set_by_id("FTMO_SWING@2026-11-02") is rule_set_for(ProviderProduct.FTMO_SWING)
        assert rule_set_by_id("nothing@1") is None
        assert ProviderProduct.EXNESS_STANDARD in products_of(Provider.EXNESS)
        assert ProviderProduct.EXNESS_STANDARD not in products_of(Provider.FTMO)

    def test_a_version_applies_from_its_date(self) -> None:
        assert rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP, date(2026, 11, 1)) is None
        assert rule_set_for(ProviderProduct.FTMO_ACCOUNT_2STEP, date(2026, 11, 2)) is not None
        assert rule_set_for(ProviderProduct.UNKNOWN) is None


class TestFtmoProducts:
    def test_one_step_has_the_three_percent_daily_limit_and_a_trailing_end_of_day_maximum(self) -> None:
        for product in (ProviderProduct.FTMO_CHALLENGE_1STEP, ProviderProduct.FTMO_ACCOUNT_1STEP):
            rules = rule_set_for(product)
            assert rules is not None and rules.daily_loss is not None and rules.max_loss is not None
            assert rules.daily_loss.percent == 3.0
            assert (rules.max_loss.percent, rules.max_loss.method) == (10.0, LossMethod.TRAILING_EOD_BALANCE)

    def test_two_step_has_the_five_percent_daily_limit_and_a_static_maximum(self) -> None:
        for product in (
            ProviderProduct.FTMO_CHALLENGE_2STEP,
            ProviderProduct.FTMO_VERIFICATION,
            ProviderProduct.FTMO_ACCOUNT_2STEP,
        ):
            rules = rule_set_for(product)
            assert rules is not None and rules.daily_loss is not None and rules.max_loss is not None
            assert rules.daily_loss.percent == 5.0
            assert (rules.max_loss.percent, rules.max_loss.method) == (10.0, LossMethod.STATIC_INITIAL)

    def test_the_day_starts_in_central_european_time_not_on_the_brokers_clock(self) -> None:
        for rule_set in RULE_SETS:
            if rule_set.daily_loss is not None:
                assert rule_set.daily_loss.timezone == "Europe/Prague"

    def test_objectives_are_the_accounts_goals_and_differ_by_phase(self) -> None:
        targets = {
            product: rule_set_for(product).profit_target_percent  # type: ignore[union-attr]
            for product in (
                ProviderProduct.FTMO_CHALLENGE_1STEP,
                ProviderProduct.FTMO_CHALLENGE_2STEP,
                ProviderProduct.FTMO_VERIFICATION,
                ProviderProduct.FTMO_ACCOUNT_1STEP,
                ProviderProduct.FTMO_ACCOUNT_2STEP,
            )
        }
        assert targets == {
            ProviderProduct.FTMO_CHALLENGE_1STEP: 10.0,
            ProviderProduct.FTMO_CHALLENGE_2STEP: 10.0,
            ProviderProduct.FTMO_VERIFICATION: 5.0,
            ProviderProduct.FTMO_ACCOUNT_1STEP: None,
            ProviderProduct.FTMO_ACCOUNT_2STEP: None,
        }
        two_step = rule_set_for(ProviderProduct.FTMO_CHALLENGE_2STEP)
        assert two_step is not None and two_step.min_trading_days == 4

    def test_news_and_overnight_restrictions_apply_to_the_account_and_not_to_the_evaluation(self) -> None:
        for product in (
            ProviderProduct.FTMO_CHALLENGE_1STEP,
            ProviderProduct.FTMO_CHALLENGE_2STEP,
            ProviderProduct.FTMO_VERIFICATION,
        ):
            rules = rule_set_for(product)
            assert rules is not None and rules.news is None and not rules.overnight.restricted
        for product in (
            ProviderProduct.FTMO_ACCOUNT_1STEP,
            ProviderProduct.FTMO_ACCOUNT_2STEP,
            ProviderProduct.FTMO_INSTANT,
        ):
            rules = rule_set_for(product)
            assert rules is not None and rules.news is not None and rules.overnight.restricted
            assert (rules.news.before_seconds, rules.news.after_seconds) == (120, 120)
            assert rules.overnight.break_longer_than_hours == 2.0

    def test_swing_is_exempt_from_both_but_its_loss_rules_are_not_sourced(self) -> None:
        swing = rule_set_for(ProviderProduct.FTMO_SWING)
        assert swing is not None
        assert swing.news is None and not swing.overnight.restricted
        assert not swing.loss_rules_sourced and swing.daily_loss is None and swing.max_loss is None
        assert swing.max_leverage == 30

    def test_what_was_read_loosely_is_flagged_for_review(self) -> None:
        instant = rule_set_for(ProviderProduct.FTMO_INSTANT)
        one_step = rule_set_for(ProviderProduct.FTMO_ACCOUNT_1STEP)
        assert instant is not None and instant.needs_review
        assert one_step is not None and one_step.needs_review

    def test_the_request_limit_of_the_forbidden_practices_page_is_recorded(self) -> None:
        assert all(
            rule_set.max_requests_per_day == 2_000 for rule_set in RULE_SETS if rule_set.provider is Provider.FTMO
        )

    def test_ftmo_is_simulated_trading_never_a_broker(self) -> None:
        assert {rule_set.execution_environment for rule_set in RULE_SETS if rule_set.provider is Provider.FTMO} == {
            "simulated"
        }


class TestExnessStandard:
    def test_exness_imposes_no_loss_limit_and_states_its_margin_levels(self) -> None:
        rules = rule_set_for(ProviderProduct.EXNESS_STANDARD)
        assert rules is not None
        assert rules.daily_loss is None and rules.max_loss is None and not rules.requires_loss_references
        assert (rules.margin_call_percent, rules.stop_out_percent) == (60.0, 0.0)
        assert rules.execution_environment == "broker" and rules.loss_rules_sourced

    def test_commission_and_swap_are_not_claimed(self) -> None:
        rules = rule_set_for(ProviderProduct.EXNESS_STANDARD)
        assert rules is not None
        assert any("commission" in item for item in rules.not_sourced)
        assert any("swap" in item for item in rules.not_sourced)


class TestTheDeclaredChallengeIsTheOnlyWayToKnowAnFtmoProduct:
    @pytest.mark.parametrize(
        ("type_", "phase", "expected"),
        [
            ("1-step", "challenge", ProviderProduct.FTMO_CHALLENGE_1STEP),
            ("2-step", "challenge", ProviderProduct.FTMO_CHALLENGE_2STEP),
            ("2-step", "verification", ProviderProduct.FTMO_VERIFICATION),
            ("1-step", "funded", ProviderProduct.FTMO_ACCOUNT_1STEP),
            ("2-step", "funded", ProviderProduct.FTMO_ACCOUNT_2STEP),
            ("instant", "funded", ProviderProduct.FTMO_INSTANT),
        ],
    )
    def test_each_declared_shape_is_its_product(self, type_: str, phase: str, expected: ProviderProduct) -> None:
        assert ftmo_product_of(ftmo(type_, phase)) is expected

    def test_swing_is_a_product_of_its_own(self) -> None:
        assert ftmo_product_of(ftmo("2-step", "funded", "swing")) is ProviderProduct.FTMO_SWING

    def test_nothing_declared_is_unknown_never_a_default_two_step(self) -> None:
        assert ftmo_product_of(None) is ProviderProduct.UNKNOWN

    def test_a_one_step_has_no_verification_so_that_shape_is_unknown(self) -> None:
        assert ftmo_product_of(ftmo("1-step", "verification")) is ProviderProduct.UNKNOWN
