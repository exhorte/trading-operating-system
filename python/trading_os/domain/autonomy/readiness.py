"""Autonomy readiness (mission § 25): before ARMED or AUTONOMOUS every critical condition must hold.
A single failed critical check means ``AUTONOMY = BLOCKED``.

The services gather ``ReadinessFacts`` (plain booleans plus a one-line detail each); this module maps them to the
sixteen checks and aggregates. Keeping it a pure mapping makes « why is autonomy blocked? » a unit-testable answer.
"""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.primitives import DomainModel


class Fact(DomainModel):
    ok: bool = False
    detail: str = "not evaluated"


class ReadinessFacts(DomainModel):
    python_core: Fact = Fact()
    database: Fact = Fact()
    mt5_connected: Fact = Fact()
    correct_account: Fact = Fact()
    symbols_available: Fact = Fact()
    risk_engine: Fact = Fact()
    sizing_valid: Fact = Fact()
    reconciliation: Fact = Fact()
    kill_switch_available: Fact = Fact()
    heartbeat: Fact = Fact()
    supervisor: Fact = Fact()
    execution_engine: Fact = Fact()
    strategy_valid: Fact = Fact()
    position_management: Fact = Fact()
    no_critical_incident: Fact = Fact()
    account_limits_configured: Fact = Fact()


class ReadinessCheck(DomainModel):
    check_id: str
    label: str
    ok: bool
    critical: bool = True
    detail: str


class ReadinessReport(DomainModel):
    ready: bool
    blockers: list[str]  # check ids that failed
    checks: list[ReadinessCheck]
    evaluated_at: datetime


# (field of ReadinessFacts, label) in the order of the mission.
_CHECKS: tuple[tuple[str, str], ...] = (
    ("python_core", "Python core healthy"),
    ("database", "Database healthy"),
    ("mt5_connected", "MT5 connected"),
    ("correct_account", "Correct account connected"),
    ("symbols_available", "Strategy symbols available"),
    ("risk_engine", "Risk Engine healthy"),
    ("sizing_valid", "Position sizing valid (broker specifications)"),
    ("reconciliation", "Reconciliation healthy"),
    ("kill_switch_available", "Kill switch available"),
    ("heartbeat", "Heartbeat active"),
    ("supervisor", "Supervisor healthy"),
    ("execution_engine", "Execution engine healthy"),
    ("strategy_valid", "Strategy valid"),
    ("position_management", "Position management valid (exits)"),
    ("no_critical_incident", "No critical incident open"),
    ("account_limits_configured", "Account limits configured by the user"),
)


def evaluate_readiness(facts: ReadinessFacts, now: datetime) -> ReadinessReport:
    checks = []
    for field, label in _CHECKS:
        fact: Fact = getattr(facts, field)
        checks.append(ReadinessCheck(check_id=field, label=label, ok=fact.ok, detail=fact.detail))
    blockers = [c.check_id for c in checks if c.critical and not c.ok]
    return ReadinessReport(ready=not blockers, blockers=blockers, checks=checks, evaluated_at=now)
