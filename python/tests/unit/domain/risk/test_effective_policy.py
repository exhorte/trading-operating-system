"""The effective risk policy: every candidate shown, the strictest binding, objectives never an input (ADR 0036)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.support.provider_fixtures import exness_standard, ftmo, ftmo_account_2step, ftmo_challenge_1step
from tests.unit.domain.test_instrument_specification import terminal_reply
from trading_os.domain.market.instrument import specification_from_terminal
from trading_os.domain.providers.identity import AccountIdentification, IdentityFacts, identify_account
from trading_os.domain.providers.rules import ProviderProduct, ProviderRuleSet, rule_set_for
from trading_os.domain.risk.dynamic_risk import RiskAllowance
from trading_os.domain.risk.effective import EffectiveRiskPolicy, LimitSource, resolve_effective_policy
from trading_os.domain.risk.policy import DrawdownPolicy, PositionLimits, RiskProfile

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def policy_for(
    facts: IdentityFacts,
    *,
    personal: RiskProfile | None = None,
    **extra: object,
) -> EffectiveRiskPolicy:
    identification = identify_account(facts)
    rule_set = rule_set_for(identification.rules_product)
    return resolve_effective_policy(
        account_id="acct",
        personal=personal or RiskProfile(),
        rule_set=rule_set,
        identification=identification,
        now=NOW,
        **extra,  # type: ignore[arg-type]
    )


def limit(policy: EffectiveRiskPolicy, key: str):
    found = policy.limit(key)
    assert found is not None, key
    return found


class TestTheStrictestWins:
    def test_a_stricter_provider_beats_the_personal_daily_loss(self) -> None:
        # The mission's example: personal 5 %, FTMO 1-Step 3 % → 3 %.
        policy = policy_for(ftmo_challenge_1step())
        daily = limit(policy, "daily_loss_percent")
        assert daily.value == 3.0 and daily.binding_source is LimitSource.PRODUCT
        assert {(c.source, c.value) for c in daily.candidates} == {
            (LimitSource.PERSONAL, 5.0),
            (LimitSource.PRODUCT, 3.0),
        }
        assert "FTMO Challenge 1-Step" in (daily.binding_origin or "")

    def test_exness_standard_keeps_the_personal_five_percent(self) -> None:
        daily = limit(policy_for(exness_standard()), "daily_loss_percent")
        assert daily.value == 5.0 and daily.binding_source is LimitSource.PERSONAL
        assert len(daily.candidates) == 1  # Exness imposes none

    def test_a_looser_provider_never_loosens_the_personal_limit(self) -> None:
        strict = RiskProfile(drawdown=DrawdownPolicy(daily_loss_limit_percent=2.0, max_drawdown_limit_percent=6.0))
        policy = policy_for(ftmo_account_2step(), personal=strict)
        assert limit(policy, "daily_loss_percent").value == 2.0
        assert limit(policy, "daily_loss_percent").binding_source is LimitSource.PERSONAL
        assert limit(policy, "max_loss_percent").value == 6.0

    def test_a_tie_names_the_contract_not_the_trader(self) -> None:
        daily = limit(policy_for(ftmo_account_2step()), "daily_loss_percent")  # 5 % and 5 %
        assert daily.value == 5.0 and daily.binding_source is LimitSource.PRODUCT

    def test_the_same_policy_for_both_providers_where_the_contract_says_nothing(self) -> None:
        for facts in (exness_standard(), ftmo_account_2step()):
            policy = policy_for(facts)
            assert limit(policy, "max_trades_per_day").value == 15
            assert limit(policy, "max_open_positions").value == 5
            assert limit(policy, "weekly_loss_percent").value == 10.0
            assert limit(policy, "risk_per_trade_percent").value == 1.5

    def test_the_candidates_of_a_personal_only_limit_are_the_personal_value(self) -> None:
        trades = limit(policy_for(exness_standard()), "max_trades_per_day")
        assert trades.binding_source is LimitSource.PERSONAL and trades.enforced_by == "gate-max-trades"


class TestRiskPerTrade:
    def allowance(self, percent: float, cap: str) -> RiskAllowance:
        return RiskAllowance(
            status="allowed",
            risk_percent=percent,
            performance_percent=-3.0,
            tier_level_percent=-3,
            grid_percent=0.2,
            binding_cap=cap,
            detail="x",
        )

    def test_the_live_allowance_is_an_account_state_candidate(self) -> None:
        policy = policy_for(exness_standard(), live_allowance=self.allowance(0.2, "grid"))
        risk = limit(policy, "risk_per_trade_percent")
        assert risk.value == 0.2 and risk.binding_source is LimitSource.ACCOUNT
        assert "grid" in (risk.binding_origin or "")

    def test_a_stopped_account_has_a_zero_allowance(self) -> None:
        stopped = RiskAllowance(
            status="stopped",
            risk_percent=0.0,
            performance_percent=-5.0,
            tier_level_percent=-5,
            grid_percent=None,
            binding_cap=None,
            reason="performance_stop_reached",
            detail="stop",
        )
        risk = limit(policy_for(exness_standard(), live_allowance=stopped), "risk_per_trade_percent")
        assert risk.value == 0.0 and "performance_stop_reached" in (risk.binding_origin or "")


class TestInstrumentLimits:
    def spec(self, **changes: object):
        spec = specification_from_terminal("EURUSDm", terminal_reply(**changes), now=NOW)
        assert spec is not None
        return spec

    def test_the_terminals_volume_maximum_binds_when_the_personal_cap_is_looser_or_absent(self) -> None:
        policy = policy_for(exness_standard(), spec=self.spec(volume_max=100.0))
        volume = limit(policy, "volume_per_order_lots")
        assert volume.value == 100.0 and volume.binding_source is LimitSource.INSTRUMENT

    def test_a_personal_cap_below_the_terminals_maximum_binds(self) -> None:
        personal = RiskProfile(positions=PositionLimits(max_volume_per_order=2.0))
        volume = limit(policy_for(exness_standard(), personal=personal, spec=self.spec()), "volume_per_order_lots")
        assert volume.value == 2.0 and volume.binding_source is LimitSource.PERSONAL

    def test_a_volume_limit_the_broker_sets_is_a_candidate_too(self) -> None:
        volume = limit(policy_for(exness_standard(), spec=self.spec(volume_limit=5.0)), "volume_per_order_lots")
        assert volume.value == 5.0 and "volume limit" in (volume.binding_origin or "")

    def test_without_a_specification_the_instrument_is_not_invented(self) -> None:
        assert limit(policy_for(exness_standard()), "volume_per_order_lots").value is None

    def test_a_personal_spread_ceiling_is_shown_when_set(self) -> None:
        assert limit(policy_for(exness_standard(), spread_cap=0.0002), "spread_ceiling").value == 0.0002
        assert limit(policy_for(exness_standard()), "spread_ceiling").value is None


class TestProviderRequestCeiling:
    def test_ftmo_states_two_thousand_requests_and_exness_none(self) -> None:
        assert limit(policy_for(ftmo_account_2step()), "requests_per_day").value == 2_000
        assert limit(policy_for(exness_standard()), "requests_per_day").value is None


class TestRestrictionsAndObjectives:
    def by_key(self, policy: EffectiveRiskPolicy):
        return {item.key: item for item in policy.restrictions}

    def test_a_funded_standard_account_carries_the_news_and_overnight_rules(self) -> None:
        items = self.by_key(policy_for(ftmo_account_2step()))
        assert items["news"].active and items["overnight"].active
        assert items["execution_environment"].informational and "simulated" in items["execution_environment"].detail
        assert "00:00 Europe/Prague" in items["loss_method"].detail

    def test_an_evaluation_phase_carries_neither(self) -> None:
        items = self.by_key(policy_for(ftmo(type_="2-step", phase="challenge")))
        assert not items["news"].active and not items["overnight"].active

    def test_objectives_are_informational_and_never_active(self) -> None:
        items = self.by_key(policy_for(ftmo(type_="2-step", phase="challenge")))
        assert items["profit_target"].informational and not items["profit_target"].active
        assert "never a reason to raise the risk" in items["profit_target"].detail
        assert items["min_trading_days"].informational

    def test_exness_margin_levels_are_documentary(self) -> None:
        items = self.by_key(policy_for(exness_standard()))
        assert (
            items["margin_levels"].informational and "terminal states the real levels" in items["margin_levels"].detail
        )

    def test_what_is_not_sourced_and_what_needs_a_review_travel_with_the_policy(self) -> None:
        policy = policy_for(ftmo_challenge_1step())
        assert any("commission" in item for item in policy.not_sourced)
        assert policy.needs_review


class TestTheIdentityOfThePolicy:
    def test_it_names_the_product_the_version_and_whether_the_account_may_trade(self) -> None:
        policy = policy_for(ftmo_account_2step())
        assert (policy.product, policy.rule_set_id, policy.rule_version) == (
            "FTMO_ACCOUNT_2STEP",
            "FTMO_ACCOUNT_2STEP@2026-11-02",
            "2026-11-02",
        )
        assert policy.executable and policy.blockers == ()

    def test_an_unidentified_account_has_a_policy_that_says_it_cannot_trade(self) -> None:
        policy = policy_for(ftmo(declared=False))
        assert not policy.executable and "account_product_unknown" in policy.blockers
        assert policy.rule_set_id is None and policy.product == "UNKNOWN"
        assert {item.key for item in policy.restrictions} == {"identity"}

    def test_no_identification_at_all_is_not_executable(self) -> None:
        policy = resolve_effective_policy(
            account_id=None, personal=RiskProfile(), rule_set=None, identification=None, now=NOW
        )
        assert not policy.executable and policy.blockers == ("account_facts_missing",)


@pytest.mark.parametrize("product", [p for p in ProviderProduct if p is not ProviderProduct.UNKNOWN])
def test_every_product_resolves_to_a_policy(product: ProviderProduct) -> None:
    rule_set: ProviderRuleSet | None = rule_set_for(product)
    assert rule_set is not None
    identification: AccountIdentification | None = None
    policy = resolve_effective_policy(
        account_id="a", personal=RiskProfile(), rule_set=rule_set, identification=identification, now=NOW
    )
    assert policy.rule_set_id == rule_set.rule_set_id and policy.limits
