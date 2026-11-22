"""The System Center (ADR 0039 § 8, I7 and I8): for each terminal the launcher registered, what its agent says, what the core knows of the account, and the
reading of the conditions of technical readiness (``shared/ea_readiness.py``).

**Read-only, and nothing here decides.** It reads: the launcher's registry (a file), the agent's hello and heartbeat, the core's identification and readiness
report, the reconciliation's last success. It raises no mode, attaches no account, sends no command, writes nothing. A fact it cannot read is ``None`` in the
reading — and an unknown fact is never green. A terminal and its agent are matched by the **login Exhorte declared** for the terminal, nothing cleverer.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from trading_os.domain.autonomy.readiness import ReadinessReport
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.execution.commands import ExecutionCommand
from trading_os.domain.providers.identity import AccountIdentification, SignalKind
from trading_os.domain.system.center import (
    AgentLiveView,
    AuthorizationView,
    ConditionView,
    Mt5TerminalView,
    ProtectionsView,
    ReadinessView,
    RegisteredTerminal,
    SystemCenterView,
)
from trading_os.infrastructure.launcher_state import read_recent_events, read_registry
from trading_os.shared.ea_readiness import EaReadiness, ReadinessInput, evaluate_ea_readiness
from trading_os.shared.time import Clock


class AgentsPort(Protocol):
    def registered_logins(self) -> list[str]: ...
    def agent_status(self, login: str) -> AgentStatus | None: ...
    def last_heartbeat(self, login: str) -> datetime | None: ...
    def registered_since(self, login: str) -> datetime | None: ...
    async def in_doubt(self, account_id: str | None = None) -> list[ExecutionCommand]: ...


class AccountsPort(Protocol):
    def is_connected(self, account_id: str) -> bool: ...


class IdentityPort(Protocol):
    async def identify(self, account_id: str) -> AccountIdentification: ...


class ReconciliationPort(Protocol):
    def last_success_at(self, account_id: str) -> datetime | None: ...


class AutonomyPort(Protocol):
    @property
    def mode(self) -> AutonomyMode: ...
    async def readiness(self, *, fresh: bool = False) -> ReadinessReport: ...


class SystemCenterService:
    def __init__(
        self,
        *,
        execution: AgentsPort,
        accounts: AccountsPort,
        providers: IdentityPort,
        reconciliation: ReconciliationPort,
        autonomy: AutonomyPort,
        clock: Clock,
        core_status: Callable[[], str],
        workers_alive: Callable[[], int],
        registry_path: Path,
        events_dir: Path,
    ) -> None:
        self._execution = execution
        self._accounts = accounts
        self._providers = providers
        self._reconciliation = reconciliation
        self._autonomy = autonomy
        self._clock = clock
        self._core_status = core_status
        self._workers_alive = workers_alive
        self._registry_path = registry_path
        self._events_dir = events_dir

    async def snapshot(self) -> SystemCenterView:
        registered, problem = read_registry(self._registry_path)
        terminals = [await self._terminal(item) for item in registered]
        known = {item.declared.expected_login for item in registered if item.declared.expected_login}
        logins = self._execution.registered_logins()
        now = self._clock.now()
        return SystemCenterView(
            observed_at=now,
            core_status=self._core_status(),
            execution_mode=self._autonomy.mode.value,
            agents_connected=len(logins),
            mt5_workers_alive=self._workers_alive(),
            terminals=terminals,
            unregistered_agents=[
                view for login in logins if login not in known if (view := self._agent_view(login, now)) is not None
            ],
            registry_problem=problem,
            recent_events=read_recent_events(self._events_dir),
        )

    async def terminals(self) -> list[Mt5TerminalView]:
        registered, _problem = read_registry(self._registry_path)
        return [await self._terminal(item) for item in registered]

    # ------------------------------------------------------------------------------------------------ one terminal

    async def _terminal(self, terminal: RegisteredTerminal) -> Mt5TerminalView:
        now = self._clock.now()
        login = terminal.declared.expected_login
        status = self._execution.agent_status(login) if login and login in self._execution.registered_logins() else None
        facts = await self._facts(terminal, status, now)
        return Mt5TerminalView(
            terminal=terminal,
            hello_received=status is not None,
            agent=self._agent_view(login, now) if status is not None and login else None,
            readiness=_readiness_view(evaluate_ea_readiness(facts)),
        )

    async def _facts(self, terminal: RegisteredTerminal, status: AgentStatus | None, now: datetime) -> ReadinessInput:
        declared = terminal.declared
        account_id = declared.account_id
        connected = self._accounts.is_connected(account_id) if account_id else None
        identification = await self._identification(account_id) if account_id and connected else None
        report = await self._autonomy.readiness(fresh=False)
        checks: dict[str, bool | None] = {item.check_id: item.ok for item in report.checks}
        login = declared.expected_login
        beat = self._execution.last_heartbeat(login) if login else None
        since = self._execution.registered_since(login) if login else None
        recon = self._reconciliation.last_success_at(account_id) if account_id else None
        doubt = len(await self._execution.in_doubt(account_id)) if account_id else None
        hello = status is not None
        return ReadinessInput(
            declared_login=login,
            declared_provider=declared.provider,
            declared_product=declared.product,
            declared_symbols=tuple(declared.allowed_symbols),
            declared_chart_symbol=declared.chart_symbol,
            terminal_running=True if hello else None,
            mt5_connected=connected,
            core_ok=self._core_status() == "ok",
            readiness_checks={
                "no_critical_incident": checks.get("no_critical_incident"),
                "account_limits_configured": checks.get("account_limits_configured"),
            },
            execution_mode=self._autonomy.mode.value,
            broker_product=identification.broker_product.value if identification else None,
            product_observed=_product_observed(identification),
            identification_blockers=tuple(item.value for item in identification.blockers) if identification else (),
            identification_executable=identification.executable if identification else None,
            hello_received=hello,
            agent_version=status.agent_version if status else None,
            capabilities=tuple(status.capabilities) if status else None,
            protocol_version=status.protocol_version if status else None,
            agent_login=status.account_login if status else None,
            identity=status.identity if status else None,
            heartbeat_age_s=(now - beat).total_seconds() if beat is not None and hello else None,
            core_silent_ms=status.core_silent_ms if status else None,
            attached_experts=tuple(status.attached_experts) if status else None,
            agent_compiled_mode=(status.mode_ceiling or "").upper() or None if status else None,
            halted=status.halted if status else None,
            tradable=status.tradable if status else None,
            reported_chart=(status.chart_symbol, status.chart_period)
            if status and status.chart_symbol and status.chart_period
            else None,
            reported_params_match=_params_match(terminal, status),
            init_state=status.init_state if status else None,
            init_issues=tuple(status.init_issues) if status else (),
            instance_id=status.instance_id if status else None,
            terminal_id=None if terminal.portable else terminal.terminal_id,
            attach_reconciled=(None if since is None else (recon is not None and recon >= since)) if hello else None,
            unresolved_commands=doubt if hello else None,
        )

    async def _identification(self, account_id: str) -> AccountIdentification | None:
        try:
            return await self._providers.identify(account_id)
        except (
            Exception
        ):  # an identification that cannot be made is an unknown fact, never a crash of the System Center
            return None

    def _agent_view(self, login: str | None, now: datetime) -> AgentLiveView | None:
        status = self._execution.agent_status(login) if login else None
        if status is None or login is None:
            return None
        beat = self._execution.last_heartbeat(login)
        protections = status.local_protections
        return AgentLiveView(
            login=status.account_login,
            agent_id=status.agent_id,
            agent_version=status.agent_version,
            mode=status.mode,
            mode_ceiling=status.mode_ceiling,
            identity=status.identity,
            heartbeat_age_s=round((now - beat).total_seconds(), 1) if beat is not None else None,
            registered_since=self._execution.registered_since(login),
            capabilities=list(status.capabilities),
            attached_experts=list(status.attached_experts),
            halted=status.halted,
            tradable=status.tradable,
            core_silent_ms=status.core_silent_ms,
            server=status.server or None,
            protocol_version=status.protocol_version,
            chart_symbol=status.chart_symbol,
            chart_period=status.chart_period,
            instance_id=status.instance_id,
            terminal_build=status.terminal_build,
            init_state=status.init_state,
            init_issues=list(status.init_issues),
            local_protections=ProtectionsView(**protections.model_dump()) if protections else None,
        )


def _product_observed(identification: AccountIdentification | None) -> bool:
    """The product of the carrier is deduced from what the terminal shows — the symbol suffix — rather than from a contract the user declared (C6).

    The identification adds a *declared* signal to the product it settles because the user declared a contract for it (an FTMO challenge); when no declared
    signal points to the carrier's product, the product stands on observation alone — and observation alone is never « confirmed »."""
    if identification is None or identification.broker_product.value == "UNKNOWN":
        return False
    product = identification.broker_product.value
    declared = any(
        signal.kind is SignalKind.DECLARED_PRODUCT and not signal.observed and signal.points_to == product
        for signal in identification.signals
    )
    return not declared


def _params_match(terminal: RegisteredTerminal, status: AgentStatus | None) -> bool | None:
    """Do the protections the agent says it loaded match what the preset was made from? ``None`` = the agent does not report them (a 1.13)."""
    if status is None or status.local_protections is None or status.local_protections.allowed_symbols is None:
        return None
    wanted = set(terminal.declared.allowed_symbols)
    if not wanted:
        return None
    if set(status.local_protections.allowed_symbols) != wanted:
        return False
    magic = status.magic_number
    return not (terminal.declared.magic is not None and magic is not None and magic != terminal.declared.magic)


def _readiness_view(result: EaReadiness) -> ReadinessView:
    return ReadinessView(
        verdict=result.verdict,
        header_code=result.header_code,
        red_codes=list(result.red_codes),
        pending_codes=list(result.pending_codes),
        warning_codes=list(result.warning_codes),
        conditions=[
            ConditionView(
                code=item.code,
                label=item.label,
                light=item.light.value,
                detail=item.detail,
                reason_codes=list(item.reason_codes),
            )
            for item in result.conditions
        ],
        execution_authorization=AuthorizationView(
            allowed=result.execution_authorization.allowed, reasons=list(result.execution_authorization.reasons)
        ),
    )
