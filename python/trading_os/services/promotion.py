"""PromotionService — measures, from the core's own records, what ``domain/autonomy/promotion`` asks about (ADR 0027).

Read-only and advisory: it computes a report and decides nothing. Every figure comes from something the core recorded (strategy
evaluations, execution commands and their state, open incidents, the readiness report, the validation reports on disk).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from trading_os.domain.autonomy.promotion import PromotionFacts, PromotionPlan, PromotionReport, promotion_steps
from trading_os.domain.autonomy.state import ExecutionRoute
from trading_os.domain.execution.commands import CommandKind, CommandState
from trading_os.domain.market.sessions import NY_TIME_ZONE
from trading_os.domain.system.supervision import Severity
from trading_os.domain.validation.report import ValidationReport
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.runtime.supervisor import Supervisor
from trading_os.services.accounts import AccountService
from trading_os.services.autonomy import AutonomyService
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

LOOKBACK = timedelta(days=30)
EXECUTED = frozenset({CommandState.EXECUTED, CommandState.RECONCILED})


class PromotionService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        autonomy: AutonomyService,
        supervisor: Supervisor,
        repos: Repositories,
        clock: Clock,
        validation_dir: Path,
        plan: PromotionPlan | None = None,
    ) -> None:
        self._accounts = accounts
        self._autonomy = autonomy
        self._supervisor = supervisor
        self._repos = repos
        self._clock = clock
        self._validation_dir = validation_dir
        self.plan = plan or PromotionPlan()

    async def report(self, account_id: str | None) -> PromotionReport:
        now = self._clock.now()
        overview = await self._autonomy.overview()
        mode = overview.effective_mode
        if account_id is None:
            facts = PromotionFacts(
                limits_configured=False, evaluation_days=0, paper_commands=0, confirmed_orders=0, commands_in_doubt=0,
                critical_incidents=0, readiness_ready=None,
            )  # fmt: skip
        else:
            facts = await self._facts(account_id, overview.readiness.ready if overview.readiness else None)
        return PromotionReport(
            account_id=account_id, mode=mode, steps=promotion_steps(facts, self.plan, mode), evaluated_at=now
        )

    async def _facts(self, account_id: str, ready: bool | None) -> PromotionFacts:
        now = self._clock.now()
        account = await self._accounts.effective(account_id)
        evaluations = await self._repos.strategy.evaluations_since(now - LOOKBACK)
        days = {e.event_at.astimezone(NY_TIME_ZONE).date() for e in evaluations if e.strategy_id == "S01"}
        commands = await self._repos.execution.recent(account_id, 500)
        opens = [c for c in commands if c.request.kind is CommandKind.OPEN]
        paper = [c for c in opens if c.route is ExecutionRoute.PAPER and c.state is CommandState.SIMULATED]
        confirmed = [
            c for c in opens if c.route in (ExecutionRoute.CONFIRM, ExecutionRoute.AUTOMATIC) and c.state in EXECUTED
        ]
        doubtful = await self._repos.execution.in_doubt(account_id)
        critical = [
            i
            for i in self._supervisor.open_incidents()
            if i.severity is Severity.CRITICAL and i.account_id in (None, account_id)
        ]
        trades, breach = self._latest_validation()
        return PromotionFacts(
            limits_configured=account.risk_profile.configured, evaluation_days=len(days), paper_commands=len(paper),
            confirmed_orders=len(confirmed), commands_in_doubt=len(doubtful), critical_incidents=len(critical),
            readiness_ready=ready, validation_trades=trades, validation_p_total_breach=breach,
            armed_days_without_halt=None,  # the history of transitions is not read here: not measured, so not met
        )  # fmt: skip

    def _latest_validation(self) -> tuple[int | None, float | None]:
        """The newest validation report of S01 on disk: how many trades, and the chance the Monte Carlo gave of reaching the total limit."""
        newest: ValidationReport | None = None
        for path in sorted(self._validation_dir.glob("validation-S01-*.json")):
            try:
                report = ValidationReport.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("promotion: the validation report %s is unreadable", path.name)
                continue
            if newest is None or report.generated_at > newest.generated_at:
                newest = report
        if newest is None:
            return None, None
        breach = newest.monte_carlo.p_total_breach if newest.monte_carlo else None
        return newest.metrics.trades, breach
