"""WhyNoTradeService — gathers what the core already knows and hands it to ``build_why`` (ADR 0028). Read-only; it decides nothing."""

from __future__ import annotations

from trading_os.domain.autonomy.why import EVALUATION_WINDOW, WhyNoTrade, build_why
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.accounts import AccountService
from trading_os.services.autonomy import AutonomyService
from trading_os.services.guardian import AccountGuardianService
from trading_os.services.risk import RiskService
from trading_os.shared.errors import Unavailable
from trading_os.shared.time import Clock


class WhyNoTradeService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        autonomy: AutonomyService,
        risk: RiskService,
        guardian: AccountGuardianService,
        repos: Repositories,
        clock: Clock,
    ) -> None:
        self._accounts = accounts
        self._autonomy = autonomy
        self._risk = risk
        self._guardian = guardian
        self._repos = repos
        self._clock = clock

    async def answer(self) -> WhyNoTrade:
        now = self._clock.now()
        overview = await self._autonomy.overview()
        account_id = self._accounts.active_account_id
        try:
            evaluations = await self._repos.strategy.evaluations_since(now - EVALUATION_WINDOW)
        except Unavailable:
            evaluations = []  # the database is down: the other sources still answer
        return build_why(
            account_id=account_id,
            mode=overview.effective_mode,
            ceiling=overview.ceiling,
            halted_reason=overview.state.halted_reason,
            readiness=overview.readiness,
            risk=self._risk.status(account_id) if account_id else None,
            evaluations=evaluations,
            guardian=self._guardian.report(account_id) if account_id else None,
            now=now,
        )
