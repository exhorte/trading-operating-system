"""The System Center (ADR 0039 § 8, I7 and I8): the launcher's registry, the agent's hello, the core's identification, put through the one reading of technical readiness.

Read-only and honest: no mode is raised, no account attached, nothing is written; a fact that cannot be read is unknown, and unknown is never green. The terminal and its
agent meet by the **login Exhorte declared**. The facts of the account are the simulated fixtures of the provider tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.support.provider_fixtures import exness_standard
from trading_os.domain.autonomy.readiness import ReadinessCheck, ReadinessReport
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.agent import AgentProtections, AgentStatus
from trading_os.domain.providers.identity import identify_account
from trading_os.services.system_center import SystemCenterService
from trading_os.shared.time import ManualClock

NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)
LOGIN = "486046157"
TERMINAL_ID = "D0E8209F77C8CF37AD8BF550E51FF075"
CAPS = ["ping", "halt", "dead_man", "limit", "modify", "close", "cancel"]


def terminal_entry(**declared: Any) -> dict[str, Any]:
    base = {
        "accountId": "exness-486046157",
        "expectedLogin": LOGIN,
        "chart": {"symbol": "XAUUSDm", "period": "M5"},
        "magic": 1001,
        "allowedSymbols": ["XAUUSDm", "EURUSDm"],
        "provider": "EXNESS",
        "product": "EXNESS_STANDARD",
    }
    base.update(declared)
    return {
        "terminalId": TERMINAL_ID,
        "label": "exness-demo",
        "installPath": r"C:\Program Files\MetaTrader 5",
        "dataPath": rf"C:\Users\trader\AppData\Roaming\MetaQuotes\Terminal\{TERMINAL_ID}",
        "portable": False,
        "source": "DISCOVERED",
        "declared": {k: v for k, v in base.items() if v is not None},
        "operation": {"kind": "IDLE"},
        "deployment": {
            "deploymentId": "d1",
            "agentVersion": "1.13",
            "ex5Sha256": "ab" * 32,
            "deployedAt": "2026-11-12T10:00:00Z",
            "expertPath": r"TradingOsAgent\TradingOsAgent",
        },
        "lastState": {"state": "EA_VALIDATING", "at": "2026-11-12T11:00:00Z", "codes": []},
        "registeredAt": "2026-11-12T09:00:00Z",
        "updatedAt": "2026-11-12T11:00:00Z",
    }


def agent(**changes: Any) -> AgentStatus:
    base: dict[str, Any] = {
        "account_login": LOGIN,
        "agent_id": "mt5-execution-agent-1001",
        "agent_version": "1.13",
        "mode": "observe",
        "mode_ceiling": "observe",
        "identity": "ok",
        "capabilities": CAPS,
        "core_silent_ms": 1500,
        "tradable": False,
        "halted": False,
        "attached_experts": [],
        "server": "Exness-MT5Trial10",
    }
    base.update(changes)
    return AgentStatus(**base)


class FakeExecution:
    def __init__(
        self, status: AgentStatus | None = None, *, beat_s: float = 3.0, registered_s: float = 600.0, doubt: int = 0
    ) -> None:
        self.status = status
        self.beat_s = beat_s
        self.registered_s = registered_s
        self.doubt = doubt

    def registered_logins(self) -> list[str]:
        return [self.status.account_login] if self.status else []

    def agent_status(self, login: str) -> AgentStatus | None:
        return self.status if self.status and self.status.account_login == login else None

    def last_heartbeat(self, login: str) -> datetime | None:
        return NOW - timedelta(seconds=self.beat_s) if self.status else None

    def registered_since(self, login: str) -> datetime | None:
        return NOW - timedelta(seconds=self.registered_s) if self.status else None

    async def in_doubt(self, account_id: str | None = None) -> list[Any]:
        return [object()] * self.doubt


class FakeAccounts:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self, account_id: str) -> bool:
        return self.connected


class FakeProviders:
    def __init__(self, **facts: Any) -> None:
        self.identification = identify_account(exness_standard(**facts))

    async def identify(self, account_id: str) -> Any:
        return self.identification


class FakeReconciliation:
    def __init__(self, ago_s: float | None = 60.0) -> None:
        self.ago_s = ago_s

    def last_success_at(self, account_id: str) -> datetime | None:
        return None if self.ago_s is None else NOW - timedelta(seconds=self.ago_s)


class FakeAutonomy:
    def __init__(self, mode: AutonomyMode = AutonomyMode.OFF, ok: bool = True) -> None:
        self._mode = mode
        self._ok = ok

    @property
    def mode(self) -> AutonomyMode:
        return self._mode

    async def readiness(self, *, fresh: bool = False) -> ReadinessReport:
        checks = [
            ReadinessCheck(check_id="no_critical_incident", label="x", ok=self._ok, detail=""),
            ReadinessCheck(check_id="account_limits_configured", label="y", ok=self._ok, detail=""),
        ]
        return ReadinessReport(ready=self._ok, blockers=[], checks=checks, evaluated_at=NOW)


def service(
    tmp_path: Path,
    *,
    entries: list[dict[str, Any]] | None = None,
    execution: FakeExecution | None = None,
    accounts: FakeAccounts | None = None,
    providers: FakeProviders | None = None,
    reconciliation: FakeReconciliation | None = None,
    autonomy: FakeAutonomy | None = None,
) -> SystemCenterService:
    registry = tmp_path / "terminals.json"
    if entries is not None:
        registry.write_text(json.dumps({"version": 1, "terminals": entries}), encoding="utf-8")
    return SystemCenterService(
        execution=execution or FakeExecution(),
        accounts=accounts or FakeAccounts(),
        providers=providers or FakeProviders(),
        reconciliation=reconciliation or FakeReconciliation(),
        autonomy=autonomy or FakeAutonomy(),
        clock=ManualClock(NOW),
        core_status=lambda: "ok",
        workers_alive=lambda: 1,
        registry_path=registry,
        events_dir=tmp_path,
    )


# ------------------------------------------------------------------------------------------------ the registry


@pytest.mark.asyncio
async def test_without_a_registry_there_is_no_terminal_and_no_problem(tmp_path: Path) -> None:
    view = await service(tmp_path).snapshot()
    assert view.terminals == [] and view.registry_problem is None and view.execution_mode == "OFF"


@pytest.mark.asyncio
async def test_a_damaged_registry_is_a_problem_not_a_crash_and_not_an_empty_truth(tmp_path: Path) -> None:
    (tmp_path / "terminals.json").write_text("{ not json", encoding="utf-8")
    view = await service(tmp_path).snapshot()
    assert view.terminals == [] and view.registry_problem and "illisible" in view.registry_problem


@pytest.mark.asyncio
async def test_a_registered_terminal_shows_what_was_declared_and_what_was_deployed(tmp_path: Path) -> None:
    (item,) = (await service(tmp_path, entries=[terminal_entry()]).snapshot()).terminals
    declared = item.terminal.declared
    assert (declared.expected_login, declared.chart_symbol, declared.chart_period, declared.magic) == (
        LOGIN,
        "XAUUSDm",
        "M5",
        1001,
    )
    assert declared.allowed_symbols == ["XAUUSDm", "EURUSDm"] and declared.product == "EXNESS_STANDARD"
    assert item.terminal.deployment is not None and item.terminal.deployment.agent_version == "1.13"
    assert item.terminal.last_state == "EA_VALIDATING" and item.terminal.operation is None


@pytest.mark.asyncio
async def test_an_agent_that_no_terminal_declares_is_listed_apart(tmp_path: Path) -> None:
    view = await service(tmp_path, entries=[], execution=FakeExecution(agent(account_login="999"))).snapshot()
    assert [a.login for a in view.unregistered_agents] == ["999"] and view.terminals == []


# ------------------------------------------------------------------------------------------------ the reading


@pytest.mark.asyncio
async def test_a_terminal_whose_agent_has_not_said_hello_is_validating_with_no_hello(tmp_path: Path) -> None:
    (item,) = (await service(tmp_path, entries=[terminal_entry()]).snapshot()).terminals
    assert not item.hello_received and item.agent is None
    assert item.readiness.verdict == "VALIDATING" and "NO_HELLO" in item.readiness.pending_codes


@pytest.mark.asyncio
async def test_a_connected_agent_with_the_declared_product_is_ready_but_not_authorized_and_the_product_is_never_confirmed(
    tmp_path: Path,
) -> None:
    (item,) = (
        await service(tmp_path, entries=[terminal_entry()], execution=FakeExecution(agent())).snapshot()
    ).terminals
    assert item.hello_received and item.agent is not None and item.agent.login == LOGIN
    assert item.readiness.verdict == "READY" and item.readiness.red_codes == []
    assert "PRODUCT_UNCONFIRMED" in item.readiness.warning_codes
    authorization = item.readiness.execution_authorization
    assert not authorization.allowed and {"SYSTEM_MODE_OFF", "AGENT_COMPILED_OBSERVE", "ACCOUNT_NOT_TRADABLE"} <= set(
        authorization.reasons
    )


@pytest.mark.asyncio
async def test_without_a_declared_product_it_is_blocked_with_the_identity_header(tmp_path: Path) -> None:
    (item,) = (
        await service(tmp_path, entries=[terminal_entry(product=None)], execution=FakeExecution(agent())).snapshot()
    ).terminals
    assert item.readiness.verdict == "BLOCKED" and "PRODUCT_UNDECLARED" in item.readiness.red_codes
    assert item.readiness.header_code == "ACCOUNT_IDENTITY_UNVERIFIED"


@pytest.mark.asyncio
async def test_an_account_that_is_not_connected_to_the_core_is_blocked_on_the_broker(tmp_path: Path) -> None:
    (item,) = (
        await service(
            tmp_path, entries=[terminal_entry()], execution=FakeExecution(agent()), accounts=FakeAccounts(False)
        ).snapshot()
    ).terminals
    assert "BROKER_NOT_CONNECTED" in item.readiness.red_codes


@pytest.mark.asyncio
async def test_the_wrong_login_on_the_terminal_is_a_mismatch(tmp_path: Path) -> None:
    entry = terminal_entry(expectedLogin="777")
    (item,) = (
        await service(
            tmp_path, entries=[entry], execution=FakeExecution(agent(account_login="777", identity="mismatch"))
        ).snapshot()
    ).terminals
    assert "MT5_ACCOUNT_MISMATCH" in item.readiness.red_codes


@pytest.mark.asyncio
async def test_a_reconciliation_older_than_the_attachment_keeps_it_validating(tmp_path: Path) -> None:
    execution = FakeExecution(agent(), registered_s=120.0)
    (before,) = (
        await service(
            tmp_path, entries=[terminal_entry()], execution=execution, reconciliation=FakeReconciliation(ago_s=600.0)
        ).snapshot()
    ).terminals
    assert before.readiness.verdict == "VALIDATING" and "RECONCILIATION_PENDING" in before.readiness.pending_codes
    (never,) = (
        await service(
            tmp_path, entries=[terminal_entry()], execution=execution, reconciliation=FakeReconciliation(ago_s=None)
        ).snapshot()
    ).terminals
    assert "RECONCILIATION_PENDING" in never.readiness.pending_codes
    (after,) = (
        await service(
            tmp_path, entries=[terminal_entry()], execution=execution, reconciliation=FakeReconciliation(ago_s=30.0)
        ).snapshot()
    ).terminals
    assert after.readiness.verdict == "READY"


@pytest.mark.asyncio
async def test_a_command_in_doubt_blocks(tmp_path: Path) -> None:
    (item,) = (
        await service(tmp_path, entries=[terminal_entry()], execution=FakeExecution(agent(), doubt=2)).snapshot()
    ).terminals
    assert item.readiness.verdict == "BLOCKED" and "UNRESOLVED_COMMANDS" in item.readiness.red_codes


@pytest.mark.asyncio
async def test_a_stale_heartbeat_is_red_and_a_slow_one_is_pending(tmp_path: Path) -> None:
    (stale,) = (
        await service(tmp_path, entries=[terminal_entry()], execution=FakeExecution(agent(), beat_s=45.0)).snapshot()
    ).terminals
    assert "HEARTBEAT_STALE" in stale.readiness.red_codes
    (slow,) = (
        await service(tmp_path, entries=[terminal_entry()], execution=FakeExecution(agent(), beat_s=20.0)).snapshot()
    ).terminals
    assert "HEARTBEAT_SLOW" in slow.readiness.pending_codes


@pytest.mark.asyncio
async def test_a_third_party_expert_blocks(tmp_path: Path) -> None:
    status = agent(attached_experts=["Ultimate_ICT_Gold_Scalper_v4.0"])
    (item,) = (
        await service(tmp_path, entries=[terminal_entry()], execution=FakeExecution(status)).snapshot()
    ).terminals
    assert "THIRD_PARTY_EA_ATTACHED" in item.readiness.red_codes


# ------------------------------------------------------------------------------------------------ agent 1.14


def agent_114(**changes: Any) -> AgentStatus:
    base: dict[str, Any] = {
        "agent_version": "1.14",
        "protocol_version": 1,
        "chart_symbol": "XAUUSDm",
        "chart_period": "M5",
        "instance_id": TERMINAL_ID,
        "terminal_build": 6230,
        "init_state": "READY",
        "local_protections": AgentProtections(allowed_symbols=["XAUUSDm", "EURUSDm"], dead_man_seconds=30),
    }
    base.update(changes)
    return agent(**base)


@pytest.mark.asyncio
async def test_a_114_agent_clears_the_chart_and_parameter_warnings(tmp_path: Path) -> None:
    (item,) = (
        await service(
            tmp_path,
            entries=[terminal_entry()],
            execution=FakeExecution(agent_114(agent_id="mt5-execution-agent-1001")),
        ).snapshot()
    ).terminals
    assert item.readiness.verdict == "READY"
    assert not {"CHART_UNVERIFIED", "PARAMETERS_UNREPORTED", "PROTOCOL_VERSION_UNREPORTED"} & set(
        item.readiness.warning_codes
    )
    assert item.agent is not None and item.agent.local_protections is not None and item.agent.chart_symbol == "XAUUSDm"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"chart_symbol": "EURUSDm"}, "CHART_MISMATCH"),
        ({"init_state": "DEGRADED", "init_issues": ["SYMBOL_NOT_AVAILABLE:XAUUSDm"]}, "EA_INIT_DEGRADED"),
        ({"instance_id": "11111111111111111111111111111111"}, "MT5_INSTANCE_MISMATCH"),
        (
            {"local_protections": AgentProtections(allowed_symbols=["GBPUSDm"], dead_man_seconds=30)},
            "PARAMETERS_MISMATCH",
        ),
        ({"protocol_version": 99}, "EA_PROTOCOL_INCOMPATIBLE"),
    ],
)
async def test_a_114_report_that_contradicts_the_declaration_is_a_red_with_its_own_code(
    tmp_path: Path, changes: dict[str, Any], code: str
) -> None:
    (item,) = (
        await service(tmp_path, entries=[terminal_entry()], execution=FakeExecution(agent_114(**changes))).snapshot()
    ).terminals
    assert item.readiness.verdict == "BLOCKED" and code in item.readiness.red_codes


# ------------------------------------------------------------------------------------------------ discipline


@pytest.mark.asyncio
async def test_the_view_holds_no_secret_and_reading_it_writes_nothing(tmp_path: Path) -> None:
    svc = service(tmp_path, entries=[terminal_entry()], execution=FakeExecution(agent_114()))

    def files() -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    before = files()
    view = await svc.snapshot()
    assert files() == before
    dumped = json.dumps(view.model_dump(mode="json", by_alias=True)).lower()
    for word in ("token", "password", "secret", "apikey", "credential"):
        assert word not in dumped


@pytest.mark.asyncio
async def test_recent_events_of_the_launcher_are_shown_and_a_damaged_line_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "events-20261112.jsonl").write_text(
        json.dumps(
            {
                "occurredAt": "2026-11-12T10:00:00Z",
                "type": "MT5_EA_DEPLOYED",
                "severity": "INFO",
                "instanceId": TERMINAL_ID,
                "diagnostic": "agent 1.13",
            }
        )
        + "\n{ broken\n",
        encoding="utf-8",
    )
    view = await service(tmp_path, entries=[]).snapshot()
    assert [e.type for e in view.recent_events] == ["MT5_EA_DEPLOYED"] and view.recent_events[
        0
    ].instance_id == TERMINAL_ID
