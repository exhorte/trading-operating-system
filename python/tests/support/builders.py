"""Small builders for domain objects, so a test states only what it is about."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_os.domain.accounts.anti_tilt import GuardReason
from trading_os.domain.accounts.models import Account, AccountType, Environment, Provider
from trading_os.domain.accounts.profiles import ProfileParams, default_rules
from trading_os.domain.accounts.rules_ledger import RuleVersion
from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.domain.execution.commands import CommandState, ExecutionCommand, ExecutionRequest
from trading_os.domain.execution.idempotency import request_fingerprint
from trading_os.domain.primitives import Side
from trading_os.domain.risk.decision import CheckResult, RiskDecision
from trading_os.domain.strategy.intent import TradeIntent
from trading_os.shared.ids import new_id

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def make_account(
    account_id: str = "EXN-1",
    *,
    login: int = 1_000_001,
    provider: Provider = Provider.EXNESS,
    environment: Environment = Environment.DEMO,
    server: str = "Exness-MT5Trial",
) -> Account:
    account_type = AccountType.DIRECT if provider is Provider.EXNESS else AccountType.PROP_CHALLENGE
    rules = default_rules(provider, ProfileParams(account_type=account_type, reference_balance=10_000))
    return Account(
        id=account_id,
        name=f"Account {account_id}",
        provider=provider,
        account_type=account_type,
        login=login,
        server=server,
        currency="USD",
        environment=environment,
        symbol_suffix="m" if provider is Provider.EXNESS else "",
        risk_profile=rules.risk_profile,
        trading_rules=rules.trading_rules,
        execution_profile=rules.execution_profile,
        created_at=NOW,
    )


def make_rule_version(account_id: str, *, requested_at: datetime, deferred: bool) -> RuleVersion:
    rules = make_account(account_id).rules
    return RuleVersion(
        version_id=new_id("rules"),
        account_id=account_id,
        rules=rules,
        requested_at=requested_at,
        deferred=deferred,
        deferral_reasons=[GuardReason(code="trades_today", account_id=account_id, count=1)] if deferred else [],
    )


def make_intent(account_id: str = "A", *, symbol: str = "EURUSDm", side: Side = Side.BUY) -> TradeIntent:
    return TradeIntent(
        intent_id=new_id("int"),
        account_id=account_id,
        strategy_id="S01",
        strategy_version="1",
        symbol=symbol,
        side=side,
        entry_price=1.1000,
        stop_loss=1.0990 if side is Side.BUY else 1.1010,
        take_profit=1.1030 if side is Side.BUY else 1.0970,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
        rationale="test",
        details={"cost_ratio": 0.1, "session": "london"},
    )


def make_decision(account_id: str = "A", *, approved: bool = True, reasons: list[str] | None = None) -> RiskDecision:
    reasons = reasons or []
    return RiskDecision(
        decision_id=new_id("risk"),
        intent_id="int-1",
        account_id=account_id,
        approved=approved,
        approved_volume=0.05 if approved else None,
        symbol="EURUSDm",
        side=Side.BUY,
        entry_price=1.1,
        stop_loss=1.099,
        take_profit=1.103,
        reasons=reasons,
        checks=[CheckResult(check_id=r, label=r.replace("_", " "), ok=False, reason=r, detail="") for r in reasons]
        or [CheckResult(check_id="news", label="No news restriction", ok=True)],
        sizing=None,
        gates=[],
        decided_at=NOW,
        expires_at=NOW + timedelta(seconds=60),
    )


def make_request(command_id: str = "cmd-test", *, account_id: str = "A", **overrides: object) -> ExecutionRequest:
    fields: dict[str, object] = {
        "command_id": command_id,
        "account_id": account_id,
        "symbol": "EURUSDm",
        "side": Side.BUY,
        "volume": 0.05,
        "stop_loss": 1.099,
        "take_profit": 1.103,
        "risk_decision_id": "risk-1",
    }
    fields.update(overrides)
    return ExecutionRequest.model_validate(fields)


def make_command(
    command_id: str = "cmd-test", *, account_id: str = "A", state: CommandState = CommandState.PENDING
) -> ExecutionCommand:
    request = make_request(command_id, account_id=account_id)
    return ExecutionCommand(
        request=request,
        fingerprint=request_fingerprint(request),
        state=state,
        route=ExecutionRoute.CONFIRM,
        mode=AutonomyMode.CONFIRM,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=60),
    )
