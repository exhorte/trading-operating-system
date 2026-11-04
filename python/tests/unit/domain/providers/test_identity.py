"""Account identification: several independent facts, never the login alone, never the user's word alone — and a safe refusal
(not executable, with the reason) whenever the account cannot be told apart. The facts here are **simulated fixtures**."""

from __future__ import annotations

from tests.support.provider_fixtures import (
    exness_standard,
    ftmo,
    ftmo_account_1step,
    ftmo_account_2step,
    ftmo_challenge_1step,
    ftmo_challenge_2step,
    ftmo_swing,
    ftmo_verification,
)
from trading_os.domain.accounts.models import Environment, FtmoChallenge, Provider
from trading_os.domain.providers.identity import (
    Confidence,
    IdentityBlocker,
    IdentityFacts,
    SignalKind,
    identify_account,
)
from trading_os.domain.providers.rules import ProviderProduct


class TestExnessStandard:
    def test_a_demo_is_identified_by_three_independent_readings_and_the_suffix(self) -> None:
        result = identify_account(exness_standard())
        assert result.provider is Provider.EXNESS and result.provider_confidence is Confidence.CONFIRMED
        assert result.broker_product is ProviderProduct.EXNESS_STANDARD
        assert result.rules_product is ProviderProduct.EXNESS_STANDARD and not result.rules_rehearsal
        assert result.account_mode == "DEMO"
        assert result.rule_set_id == "EXNESS_STANDARD@2026-11-03"
        assert result.executable and result.blockers == () and not result.needs_confirmation
        kinds = {signal.kind for signal in result.signals}
        assert {SignalKind.SERVER, SignalKind.COMPANY, SignalKind.TERMINAL_COMPANY, SignalKind.SYMBOL_SUFFIX} <= kinds

    def test_a_real_account_is_real_and_stands_on_its_own_facts(self) -> None:
        result = identify_account(exness_standard(real=True))
        assert result.account_mode == "REAL" and result.executable

    def test_a_declared_demo_on_a_real_terminal_is_refused(self) -> None:
        result = identify_account(exness_standard(real=True, declared_environment=Environment.DEMO))
        assert IdentityBlocker.ENVIRONMENT_MISMATCH in result.blockers
        assert not result.executable and result.needs_confirmation

    def test_a_declared_real_on_a_demo_terminal_is_refused_too(self) -> None:
        result = identify_account(exness_standard(declared_environment=Environment.LIVE))
        assert IdentityBlocker.ENVIRONMENT_MISMATCH in result.blockers and not result.executable

    def test_a_contest_account_counts_as_a_demo(self) -> None:
        assert identify_account(exness_standard(trade_mode="contest")).account_mode == "DEMO"

    def test_without_the_standard_suffix_the_product_is_not_identified(self) -> None:
        for suffixes in ((), ("",), ("c",), ("m", "c")):
            result = identify_account(exness_standard(observed_suffixes=suffixes))
            assert result.broker_product is ProviderProduct.UNKNOWN
            assert IdentityBlocker.PRODUCT_UNKNOWN in result.blockers and not result.executable
            assert result.needs_confirmation


class TestFtmoProducts:
    def test_each_declared_product_is_identified_and_simulated(self) -> None:
        expected = {
            ProviderProduct.FTMO_CHALLENGE_1STEP: ftmo_challenge_1step(),
            ProviderProduct.FTMO_CHALLENGE_2STEP: ftmo_challenge_2step(),
            ProviderProduct.FTMO_VERIFICATION: ftmo_verification(),
            ProviderProduct.FTMO_ACCOUNT_1STEP: ftmo_account_1step(),
            ProviderProduct.FTMO_ACCOUNT_2STEP: ftmo_account_2step(),
        }
        for product, facts in expected.items():
            result = identify_account(facts)
            assert result.provider is Provider.FTMO and result.provider_confidence is Confidence.CONFIRMED
            assert result.rules_product is product and result.product_confidence is Confidence.CONFIRMED
            assert result.account_mode == "SIMULATED", (
                "FTMO is simulated trading whatever the terminal's trade mode says"
            )
            assert result.executable, result.summary

    def test_an_ftmo_account_whose_product_nobody_declared_is_not_executable(self) -> None:
        result = identify_account(ftmo(declared=False))
        assert result.rules_product is ProviderProduct.UNKNOWN
        assert IdentityBlocker.PRODUCT_UNKNOWN in result.blockers
        assert not result.executable and result.needs_confirmation

    def test_a_one_step_verification_is_a_shape_that_does_not_exist(self) -> None:
        result = identify_account(ftmo(type_="1-step", phase="verification"))
        assert IdentityBlocker.PRODUCT_UNKNOWN in result.blockers and not result.executable

    def test_swing_is_identified_but_its_rules_are_not_sourced_so_it_cannot_trade(self) -> None:
        result = identify_account(ftmo_swing())
        assert result.rules_product is ProviderProduct.FTMO_SWING
        assert result.blockers == (IdentityBlocker.RULES_UNSOURCED,)
        assert not result.executable

    def test_a_leverage_the_declared_product_cannot_have_contradicts_it(self) -> None:
        result = identify_account(ftmo_account_2step(leverage=500))
        assert IdentityBlocker.LEVERAGE_CONTRADICTS in result.blockers and not result.executable
        assert any("1:500" in conflict for conflict in result.conflicts)

    def test_a_swing_declared_on_a_standard_leverage_is_contradicted(self) -> None:
        result = identify_account(ftmo_swing(leverage=100))
        assert IdentityBlocker.LEVERAGE_CONTRADICTS in result.blockers


class TestTheProviderIsNeverTakenOnASingleWord:
    def test_the_login_alone_identifies_nothing(self) -> None:
        result = identify_account(IdentityFacts(login=477_029_930))
        assert result.provider is None and result.provider_confidence is Confidence.NONE
        assert {IdentityBlocker.PROVIDER_NOT_IDENTIFIED, IdentityBlocker.FACTS_MISSING} <= set(result.blockers)
        assert not result.executable

    def test_a_provider_we_do_not_know_is_not_executable(self) -> None:
        result = identify_account(
            exness_standard(server="OtherBroker-Demo", company="Other Broker Ltd", terminal_company="Other Broker Ltd")
        )
        assert result.provider is None and IdentityBlocker.PROVIDER_NOT_IDENTIFIED in result.blockers
        assert not result.executable

    def test_one_match_among_readings_that_name_nobody_we_know_is_not_the_account(self) -> None:
        result = identify_account(exness_standard(server="OtherBroker-Demo", company="Other Broker Ltd"))
        assert result.provider_confidence is Confidence.WEAK and not result.executable
        assert any("name no provider we know" in conflict for conflict in result.conflicts)

    def test_names_that_point_to_two_providers_are_ambiguous(self) -> None:
        result = identify_account(exness_standard(company="FTMO Global Markets Ltd"))
        assert result.provider is None and result.provider_confidence is Confidence.CONFLICT
        assert IdentityBlocker.PROVIDER_AMBIGUOUS in result.blockers and not result.executable

    def test_a_declared_provider_the_terminal_contradicts_is_a_conflict_not_obeyed(self) -> None:
        result = identify_account(exness_standard(declared_provider=Provider.FTMO))
        assert result.provider is Provider.EXNESS and result.provider_confidence is Confidence.CONFLICT
        assert IdentityBlocker.PROVIDER_MISMATCH in result.blockers and not result.executable

    def test_one_reading_without_a_declaration_is_weak_and_not_enough_to_trade(self) -> None:
        result = identify_account(
            exness_standard(company="Some Company", terminal_company=None, declared_provider=None)
        )
        assert result.provider is Provider.EXNESS and result.provider_confidence is Confidence.WEAK
        assert IdentityBlocker.PROVIDER_NOT_IDENTIFIED in result.blockers and not result.executable

    def test_one_reading_that_the_declaration_repeats_is_probable_and_enough(self) -> None:
        result = identify_account(exness_standard(company="Some Company", terminal_company=None))
        assert result.provider_confidence is Confidence.PROBABLE and result.executable

    def test_a_terminal_that_gave_no_leverage_or_currency_is_not_executable(self) -> None:
        for missing in ("leverage", "currency", "server", "company"):
            result = identify_account(exness_standard(**{missing: None}))
            assert IdentityBlocker.FACTS_MISSING in result.blockers and not result.executable, missing


class TestRehearsalOfAnotherContract:
    """ADR 0020: an Exness *demo* may follow the FTMO profile. The carrier stays Exness; the contract applied is FTMO's."""

    def rehearsal(self, **changes: object) -> IdentityFacts:
        challenge = FtmoChallenge.model_validate({"type": "2-step", "accountSize": 10_000, "phase": "challenge"})
        return exness_standard(challenge=challenge, **changes)

    def test_the_carrier_is_exness_and_the_rules_are_ftmos(self) -> None:
        result = identify_account(self.rehearsal())
        assert result.provider is Provider.EXNESS and result.broker_product is ProviderProduct.EXNESS_STANDARD
        assert result.rules_product is ProviderProduct.FTMO_CHALLENGE_2STEP and result.rules_rehearsal
        assert result.account_mode == "DEMO" and result.executable

    def test_it_is_refused_on_a_real_account(self) -> None:
        result = identify_account(self.rehearsal(real=True))
        assert IdentityBlocker.RULES_ON_REAL_ACCOUNT in result.blockers and not result.executable

    def test_a_different_leverage_does_not_contradict_a_rehearsal(self) -> None:
        result = identify_account(self.rehearsal(leverage=2000))
        assert IdentityBlocker.LEVERAGE_CONTRADICTS not in result.blockers
        assert result.executable


def test_the_summary_says_why_an_account_cannot_trade() -> None:
    result = identify_account(ftmo(declared=False))
    assert "not executable" in result.summary and "product" in result.summary
    assert identify_account(exness_standard()).summary.endswith("executable")
