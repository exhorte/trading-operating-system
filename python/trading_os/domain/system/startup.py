"""« Démarrer le système » (ADR 0034): the vocabulary of the start-up sequence and of the verdict « may the system take a position? ».

Three things are kept apart on purpose:

* **A — the application** (core, database, cockpit) is up: it authorises no order;
* **B — the trading system** is started: engines verified, the broker reconciled, the autonomy ladder climbed to OBSERVE (or, if
  asked, PAPER / CONFIRM) — never higher;
* **C — automatic trading** is authorised: a separate gesture, one rung at a time, with the readiness green *then*.

This module is models only: the service that gathers the facts is ``services/startup.py``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from trading_os.domain.accounts.models import Environment
from trading_os.domain.autonomy.plan_modes import ModeRights, PlanMode
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.primitives import DomainModel

REAL_ACCOUNT_BANNER = "COMPTE RÉEL — LES ORDRES PEUVENT ENTRAÎNER UNE PERTE FINANCIÈRE"

# What « start » may climb to. Everything above is the separate « authorise automatic trading » gesture.
START_TARGETS = (AutonomyMode.OBSERVE, AutonomyMode.PAPER, AutonomyMode.CONFIRM)


class StartupStageState(StrEnum):
    STOPPED = "STOPPED"  # not running (and not meant to be, in this mode or without an account)
    STARTING = "STARTING"  # the start-up sequence is on it, or it has not completed its first cycle
    READY = "READY"  # verified and available, not in use
    RUNNING = "RUNNING"  # verified and working
    DEGRADED = "DEGRADED"  # works, impaired: stale data, a job running late, a silent agent
    FAILED = "FAILED"  # does not work
    HALTED = "HALTED"  # the system is halted: new entries are cut


class StartupStage(DomainModel):
    stage_id: str
    order: int
    label: str
    state: StartupStageState
    detail: str
    blocking: bool = False  # a red here stops the start-up sequence itself (no database, no account, no terminal)


class EntryCheck(DomainModel):
    """One condition that must hold before the system takes a position (mission § 2.2)."""

    check_id: str
    label: str
    ok: bool
    detail: str
    source: Literal["readiness", "startup"]


class StartupRunState(StrEnum):
    RUNNING = "RUNNING"
    DONE = "DONE"  # reached the mode that was asked for
    PARTIAL = "PARTIAL"  # started, but stopped below the asked mode (a check was red): see ``message``
    BLOCKED = "BLOCKED"  # could not start: the system is still OFF


class StartupRun(DomainModel):
    run_id: str
    state: StartupRunState
    target_mode: AutonomyMode
    started_at: datetime
    finished_at: datetime | None = None
    current_stage: str | None = None
    reached_mode: AutonomyMode | None = None
    message: str = ""
    blocked_on: list[str] = Field(default_factory=list)  # stage ids or check ids that stopped it


class AccountPanel(DomainModel):
    """The configuration screen's facts about the selected account — never a secret (the terminal keeps the password, ADR 0013)."""

    account_id: str
    name: str
    provider: str
    server: str
    account_type: str
    environment: Environment
    currency: str
    login_masked: str
    connected: bool
    status: str
    status_detail: str | None = None
    balance: float | None = None
    equity: float | None = None
    leverage: int | None = None
    terminal_trade_allowed: bool | None = None
    trading_enabled: bool  # the user's « Enable / Disable Trading » switch
    agent_connected: bool = False
    agent_tradable: bool | None = None
    ceiling: AutonomyMode  # the highest rung this account may reach (the user raises it, per account)


class StartupStatus(DomainModel):
    evaluated_at: datetime
    run: StartupRun | None = None
    stages: list[StartupStage]
    checks: list[EntryCheck]
    checks_green: bool  # every condition of § 2.2 holds
    blockers: list[str]  # the ids of the checks that do not
    mode: AutonomyMode
    plan_mode: PlanMode
    rights: ModeRights
    ladder: list[ModeRights]
    ceiling: AutonomyMode
    halted: bool
    halted_reason: str | None = None
    entries_authorized: (
        bool  # the system may take a position right now: a mode that sends orders, and every check green
    )
    entries_reason: str  # why, in one line
    real_account: bool
    real_account_banner: str | None = None
    account: AccountPanel | None = None
    can_start: bool
    next_automatic_mode: AutonomyMode | None = None  # the rung « authorise automatic trading » would climb to, if any
    can_authorize_automatic: bool = False
    authorize_blockers: list[str] = Field(default_factory=list)
