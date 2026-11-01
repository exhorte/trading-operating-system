"""What the broker's own names and figures mean (ADR 0020): provider, demo or real, how the instruments are spelled, and what
the capital can honestly be taken to be."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_os.domain.accounts.discovery import (
    broker_name_of,
    capital_proposal,
    environment_of,
    recognise_provider,
    suffix_of,
    suggested_name,
)
from trading_os.domain.accounts.models import Environment, Provider


class TestRecogniseProvider:
    @pytest.mark.parametrize(
        ("server", "company", "expected"),
        [
            ("Exness-MT5Trial10", "Exness Technologies Ltd", Provider.EXNESS),
            ("Exness-MT5Real8", "", Provider.EXNESS),
            ("FTMO-Server3", "FTMO S.R.O.", Provider.FTMO),
            ("ftmo-demo", "", Provider.FTMO),
            ("ICMarkets-Demo", "Raw Trading Ltd", None),
        ],
    )
    def test_from_the_brokers_own_names(self, server: str, company: str, expected: Provider | None) -> None:
        assert recognise_provider(server, company) is expected

    def test_two_providers_in_the_names_is_not_a_recognition(self) -> None:
        assert recognise_provider("Exness-FTMO-bridge", "") is None


class TestEnvironment:
    @pytest.mark.parametrize(
        ("trade_mode", "expected"),
        [(0, Environment.DEMO), (1, Environment.DEMO), (2, Environment.LIVE), (9, None)],
    )
    def test_from_the_trade_mode(self, trade_mode: int, expected: Environment | None) -> None:
        assert environment_of(trade_mode) is expected


class TestSymbolSpelling:
    def test_the_exness_standard_suffix(self) -> None:
        names = ["EURUSDm", "GBPUSDm", "XAUUSDm", "BTCUSDm"]
        assert broker_name_of("EURUSD", names) == "EURUSDm" and broker_name_of("XAUUSD", names) == "XAUUSDm"

    def test_a_plain_spelling_wins_over_a_suffixed_one(self) -> None:
        assert broker_name_of("EURUSD", ["EURUSDm", "EURUSD", "EURUSDc"]) == "EURUSD"

    def test_the_shortest_suffix_wins_among_suffixed_ones(self) -> None:
        assert broker_name_of("XAUUSD", ["XAUUSD.pro", "XAUUSDm"]) == "XAUUSDm"

    def test_a_longer_unrelated_name_is_not_the_instrument(self) -> None:
        assert broker_name_of("EURUSD", ["EURUSDollarIndexFuture"]) is None
        assert broker_name_of("XAUUSD", ["EURUSDm"]) is None

    def test_the_shared_suffix_and_a_warning_for_an_instrument_that_departs_from_it(self) -> None:
        assert suffix_of({"EURUSD": "EURUSDm", "XAUUSD": "XAUUSDm"}) == ("m", [])
        suffix, odd = suffix_of({"EURUSD": "EURUSDm", "XAUUSD": "XAUUSD"})
        assert suffix == "m" and len(odd) == 1 and "XAUUSD" in odd[0]
        assert suffix_of({}) == (None, [])

    def test_no_suffix_is_the_empty_string_not_none(self) -> None:
        assert suffix_of({"EURUSD": "EURUSD", "XAUUSD": "XAUUSD"}) == ("", [])


class TestCapital:
    def test_a_first_deposit_is_evidence(self) -> None:
        at = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)
        proposal = capital_proposal((10_000.0, at), balance=9_640.25)
        assert (proposal.amount, proposal.source, proposal.at, proposal.reliable) == (
            10_000.0,
            "first_deposit",
            at,
            True,
        )

    def test_a_balance_that_has_moved_is_only_a_proposal(self) -> None:
        proposal = capital_proposal(None, balance=9_640.256)
        assert (proposal.amount, proposal.source, proposal.at, proposal.reliable) == (
            9_640.26,
            "current_balance",
            None,
            False,
        )


class TestSuggestedName:
    def test_names_the_broker_the_login_and_the_demo(self) -> None:
        assert (
            suggested_name(Provider.EXNESS, "Exness Technologies Ltd", 123456789, Environment.DEMO)
            == "Exness 123456789 démo"
        )
        assert suggested_name(Provider.FTMO, "", 1510, Environment.LIVE) == "Ftmo 1510"
        assert suggested_name(None, "Other Broker Ltd", 7, None) == "Other 7"
        assert suggested_name(None, "", 7, None) == "MT5 7"
