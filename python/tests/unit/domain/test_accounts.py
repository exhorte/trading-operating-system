"""Accounts: no secret in the model, provider profiles (FTMO ≠ Exness), the anti-tilt guard and the rules ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from trading_os.domain.accounts.anti_tilt import (
    ACTIVE_LOCKOUT,
    NO_LIVE_ACCOUNT,
    OPEN_POSITIONS,
    TRADES_TODAY,
    GuardDecision,
    LiveLink,
    SessionFact,
    decide,
)
from trading_os.domain.accounts.models import (
    Account,
    AccountRules,
    AccountType,
    Environment,
    ExecutionProfile,
    FtmoChallenge,
    Provider,
    TradingRules,
)
from trading_os.domain.accounts.profiles import PROFILES, ProfileParams, default_rules
from trading_os.domain.accounts.rules_ledger import (
    CancelOutcome,
    DayAnchorState,
    RuleVersion,
    VersionStatus,
    cancel_outcome,
    is_in_effect,
    new_version,
    next_day_anchor,
    resolve_rules,
    version_status,
)
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.risk.policy import DrawdownPolicy, RiskProfile
from trading_os.shared.errors import ValidationFailed


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


NOW = utc(2026, 9, 23, 12, 0)
TODAY = utc(2026, 9, 23, 0, 0)  # the account's trading-day anchor
TOMORROW = utc(2026, 9, 24, 0, 0)
FAKE_LOGIN = 1000001  # test fixtures never use a real account number


def account(**overrides: object) -> Account:
    rules = default_rules(Provider.EXNESS, ProfileParams(account_type=AccountType.DIRECT))
    base: dict[str, object] = {
        "id": "EXNESS_DEMO_01",
        "name": "Exness demo",
        "provider": Provider.EXNESS,
        "account_type": AccountType.DIRECT,
        "login": FAKE_LOGIN,
        "server": "Test-Server",
        "currency": "USD",
        "environment": Environment.DEMO,
        "symbol_suffix": "m",
        "risk_profile": rules.risk_profile,
        "trading_rules": rules.trading_rules,
        "execution_profile": rules.execution_profile,
        "created_at": NOW,
    }
    base.update(overrides)
    return Account(**base)


class TestAccountModel:
    def test_there_is_no_place_for_a_secret(self) -> None:
        fields = set(Account.model_fields)
        assert not {"password", "secret", "token", "api_key", "credentials", "passwd"} & fields

    def test_wire_format_is_camel_case_and_round_trips(self) -> None:
        dumped = account().model_dump(mode="json", by_alias=True)
        assert {"accountType", "terminalPath", "tradingEnabled", "riskProfile", "tradingRules"} <= set(dumped)
        assert Account.model_validate(dumped) == account()

    def test_id_login_and_currency_are_validated(self) -> None:
        for bad in ("", "a", "has space", "-lead", "x" * 49):
            with pytest.raises(ValidationError):
                account(id=bad)
        assert account(id="FTMO_FUNDED_02").id == "FTMO_FUNDED_02"
        assert account(id="1000001").id == "1000001"  # legacy accounts keep their login as id, so history stays linked
        with pytest.raises(ValidationError):
            account(login=0)
        with pytest.raises(ValidationError):
            account(currency="US")

    def test_a_new_account_can_never_exceed_observe(self) -> None:
        assert account().execution_profile.max_mode is AutonomyMode.OBSERVE
        assert account().status.value == "DISCONNECTED" and account().trading_enabled

    def test_rules_round_trip_through_with_rules(self) -> None:
        other = default_rules(Provider.EXNESS, ProfileParams(account_type=AccountType.DIRECT, reference_balance=5000.0))
        updated = account().with_rules(other)
        assert updated.rules == other and updated.id == account().id


class TestProviderProfiles:
    def test_exness_direct_account(self) -> None:
        rules = default_rules(
            Provider.EXNESS, ProfileParams(account_type=AccountType.DIRECT, reference_balance=40_000.0)
        )
        assert rules.risk_profile.drawdown.reference_balance == 40_000.0
        assert rules.execution_profile.limits.commission_per_lot_round_trip == 0.0
        assert rules.trading_rules.challenge is None and rules.trading_rules.profit_target_percent is None
        assert PROFILES[Provider.EXNESS].symbol_suffix == "m"

    def test_exness_without_a_reference_keeps_it_unset_rather_than_inventing_one(self) -> None:
        rules = default_rules(Provider.EXNESS, ProfileParams(account_type=AccountType.DIRECT))
        assert rules.risk_profile.drawdown.reference_balance is None

    def test_ftmo_challenge_fixes_the_reference_to_the_challenge_size(self) -> None:
        challenge = FtmoChallenge(type="2-step", account_size=25_000, phase="challenge")
        rules = default_rules(
            Provider.FTMO, ProfileParams(account_type=AccountType.PROP_CHALLENGE, challenge=challenge)
        )
        assert rules.risk_profile.drawdown.reference_balance == 25_000
        assert rules.execution_profile.limits.commission_per_lot_round_trip == 5.0
        assert (rules.trading_rules.min_trading_days, rules.trading_rules.profit_target_percent) == (4, 10.0)
        assert PROFILES[Provider.FTMO].symbol_suffix == ""

    def test_unsourced_phases_are_not_guessed(self) -> None:
        funded = FtmoChallenge(type="2-step", account_size=100_000, phase="funded")
        rules = default_rules(Provider.FTMO, ProfileParams(account_type=AccountType.PROP_FUNDED, challenge=funded))
        assert rules.trading_rules.min_trading_days is None and rules.trading_rules.profit_target_percent is None

    def test_ftmo_and_exness_do_not_get_the_same_policy(self) -> None:
        ftmo = default_rules(Provider.FTMO, ProfileParams(account_type=AccountType.PROP_CHALLENGE))
        exness = default_rules(Provider.EXNESS, ProfileParams(account_type=AccountType.DIRECT))
        assert ftmo != exness
        assert ftmo.risk_profile.drawdown.reference_balance != exness.risk_profile.drawdown.reference_balance
        assert ftmo.execution_profile.limits != exness.execution_profile.limits

    def test_provider_and_account_type_must_agree(self) -> None:
        with pytest.raises(ValidationFailed) as caught:
            default_rules(Provider.FTMO, ProfileParams(account_type=AccountType.DIRECT))
        assert caught.value.code == "account_type_not_allowed"
        with pytest.raises(ValidationFailed):
            default_rules(Provider.EXNESS, ProfileParams(account_type=AccountType.PROP_FUNDED))

    def test_a_challenge_phase_must_match_the_account_type(self) -> None:
        verification = FtmoChallenge(type="2-step", account_size=10_000, phase="verification")
        with pytest.raises(ValidationFailed) as caught:
            default_rules(Provider.FTMO, ProfileParams(account_type=AccountType.PROP_CHALLENGE, challenge=verification))
        assert caught.value.code == "phase_mismatch"

    def test_bounds_refuse_a_typo_that_would_disable_a_gate(self) -> None:
        with pytest.raises(ValidationError):
            FtmoChallenge(type="2-step", account_size=10, phase="challenge")
        with pytest.raises(ValidationError):
            DrawdownPolicy(reference_balance=1e12)
        assert TradingRules().allowed_symbols is None


class TestAntiTiltGuard:
    """When does a change to an account's rules apply: at once, or at the next trading day (ADR 0007)?"""

    quiet = LiveLink(connected=True, account_id="ACC-A", open_positions=0)

    def session(self, account_id: str, trades: int = 0, lockout: str | None = None) -> SessionFact:
        return SessionFact(
            account_id=account_id, day_anchor_starts_at_utc=TODAY, trades_today=trades, active_lockout_reason=lockout
        )

    def test_applies_at_once_when_flat_and_nothing_happened_today(self) -> None:
        decision = decide(self.quiet, [self.session("ACC-A")])
        assert not decision.deferred and decision.reasons == []

    def test_defers_after_a_trade_since_the_day_anchor(self) -> None:
        decision = decide(self.quiet, [self.session("ACC-A", trades=2)])
        assert decision.deferred and len(decision.reasons) == 1
        reason = decision.reasons[0]
        assert (reason.code, reason.account_id, reason.count) == (TRADES_TODAY, "ACC-A", 2)

    def test_defers_while_a_position_is_open(self) -> None:
        decision = decide(self.quiet.model_copy(update={"open_positions": 1}), [])
        assert decision.deferred and decision.reasons[0].code == OPEN_POSITIONS and decision.reasons[0].count == 1

    def test_defers_while_a_lockout_is_active(self) -> None:
        decision = decide(self.quiet, [self.session("ACC-A", lockout="Daily loss guard")])
        assert decision.reasons[0].code == ACTIVE_LOCKOUT and decision.reasons[0].detail == "Daily loss guard"

    def test_defers_when_no_account_is_live(self) -> None:
        assert decide(LiveLink(connected=False, account_id="ACC-A"), []).reasons[0].code == NO_LIVE_ACCOUNT
        assert decide(LiveLink(connected=True, account_id=None), []).reasons[0].code == NO_LIVE_ACCOUNT

    def test_looks_at_every_account_not_only_the_one_connected(self) -> None:
        # The loophole: trade A, switch the terminal to a quiet B, loosen A's rules, switch back — same day.
        decision = decide(self.quiet, [self.session("ACC-A"), self.session("ACC-B", trades=3)])
        assert decision.deferred and [r.account_id for r in decision.reasons] == ["ACC-B"]

    def test_lists_every_reason_in_a_stable_order(self) -> None:
        decision = decide(
            self.quiet.model_copy(update={"open_positions": 2}),
            [self.session("b", lockout="Kill switch"), self.session("a", trades=1)],
        )
        assert [r.code for r in decision.reasons] == [OPEN_POSITIONS, TRADES_TODAY, ACTIVE_LOCKOUT]
        assert [r.account_id for r in decision.reasons] == ["ACC-A", "a", "b"]


class TestRulesLedger:
    default = default_rules(Provider.EXNESS, ProfileParams(account_type=AccountType.DIRECT))

    def rules(self, reference: float | None) -> AccountRules:
        return AccountRules(
            risk_profile=RiskProfile(drawdown=DrawdownPolicy(reference_balance=reference)),
            trading_rules=TradingRules(),
            execution_profile=ExecutionProfile(),
        )

    def version(
        self,
        vid: str,
        requested: datetime,
        reference: float | None = 5000.0,
        *,
        deferred: bool = False,
        cancelled: datetime | None = None,
    ) -> RuleVersion:
        return RuleVersion(
            version_id=vid,
            account_id="ACC-A",
            rules=self.rules(reference),
            requested_at=requested,
            deferred=deferred,
            cancelled_at=cancelled,
        )

    def test_an_immediate_change_is_in_effect(self) -> None:
        assert is_in_effect(self.version("v", NOW), TODAY)
        assert is_in_effect(self.version("v", NOW), None)

    def test_a_deferred_change_waits_for_an_anchor_after_the_request(self) -> None:
        v = self.version("v", NOW, deferred=True)
        assert not is_in_effect(v, TODAY)  # today's anchor is before the request
        assert is_in_effect(v, TOMORROW)
        assert not is_in_effect(v, None)  # no anchor known: the conservative reading

    def test_a_cancelled_change_is_never_in_effect(self) -> None:
        assert not is_in_effect(self.version("v", NOW, cancelled=NOW), TOMORROW)

    def test_resolution_prefers_the_latest_version_in_effect_and_reports_the_pending_one(self) -> None:
        applied = self.version("applied", NOW - timedelta(days=3), 5000.0)
        pending = self.version("pending", NOW, 9000.0, deferred=True)
        resolution = resolve_rules([applied, pending], TODAY, self.default)
        assert resolution.rules.risk_profile.drawdown.reference_balance == 5000.0
        assert resolution.source == applied and resolution.pending == pending
        tomorrow = resolve_rules([applied, pending], TOMORROW, self.default)
        assert tomorrow.rules.risk_profile.drawdown.reference_balance == 9000.0 and tomorrow.pending is None

    def test_with_nothing_in_effect_the_built_in_defaults_apply(self) -> None:
        resolution = resolve_rules([], TODAY, self.default)
        assert resolution.rules == self.default and resolution.source is None and resolution.pending is None

    def test_an_older_pending_change_does_not_resurface_under_a_newer_applied_one(self) -> None:
        old_pending = self.version("old", NOW - timedelta(days=2), 1000.0, deferred=True)
        newer = self.version("newer", NOW, 2000.0)
        resolution = resolve_rules([old_pending, newer], None, self.default)
        assert resolution.source == newer and resolution.pending is None

    def test_statuses(self) -> None:
        applied = self.version("applied", NOW - timedelta(days=3))
        old = self.version("old", NOW - timedelta(days=5))
        pending = self.version("pending", NOW, deferred=True)
        gone = self.version("gone", NOW, deferred=True, cancelled=NOW)
        resolution = resolve_rules([applied, old, pending, gone], TODAY, self.default)
        assert version_status(applied, resolution) is VersionStatus.IN_EFFECT
        assert version_status(old, resolution) is VersionStatus.SUPERSEDED
        assert version_status(pending, resolution) is VersionStatus.PENDING
        assert version_status(gone, resolution) is VersionStatus.CANCELLED

    def test_cancel_outcomes_are_the_four_refusals_of_the_original(self) -> None:
        assert cancel_outcome(None) is CancelOutcome.NOT_FOUND
        assert cancel_outcome(self.version("v", NOW)) is CancelOutcome.NOT_DEFERRED
        assert cancel_outcome(self.version("v", NOW, deferred=True, cancelled=NOW)) is CancelOutcome.ALREADY_CANCELLED
        started = self.version("v", NOW, deferred=True).model_copy(update={"day_started_since": True})
        assert cancel_outcome(started) is CancelOutcome.ALREADY_IN_EFFECT
        assert cancel_outcome(self.version("v", NOW, deferred=True)) is CancelOutcome.CANCELLED

    def test_new_version_records_the_guard_reasons(self) -> None:
        decision = decide(LiveLink(connected=False, account_id=None), [])
        version = new_version("ACC-A", self.rules(1234.0), decision, NOW)
        assert (
            version.deferred and version.deferral_reasons[0].code == NO_LIVE_ACCOUNT and version.account_id == "ACC-A"
        )
        assert not new_version("ACC-A", self.rules(1234.0), GuardDecision(deferred=False, reasons=[]), NOW).deferred

    def test_the_day_anchor_never_steps_back_within_an_account(self) -> None:
        current = DayAnchorState(account_id="A", starts_at_utc=TOMORROW)
        assert next_day_anchor(current, DayAnchorState(account_id="A", starts_at_utc=TODAY)) == current
        assert next_day_anchor(current, DayAnchorState(account_id="A", starts_at_utc=None)) == current
        later = DayAnchorState(account_id="A", starts_at_utc=TOMORROW + timedelta(days=1))
        assert next_day_anchor(current, later) == later

    def test_another_account_replaces_the_anchor_outright(self) -> None:
        current = DayAnchorState(account_id="A", starts_at_utc=TOMORROW)
        other = DayAnchorState(account_id="B", starts_at_utc=TODAY)  # B's server clock may be hours behind
        assert next_day_anchor(current, other) == other
        assert next_day_anchor(None, other) == other
