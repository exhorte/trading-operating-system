"""Repositories: explicit SQL, one class per aggregate, domain models in and out. ``Repositories`` is the bundle the
application container builds once from the ``Database``."""

from __future__ import annotations

from dataclasses import dataclass

from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.database.repositories.accounts import (
    AccountRepository,
    RuleVersionRepository,
    SystemStateRepository,
)
from trading_os.infrastructure.database.repositories.events import EventStore, IncidentRepository
from trading_os.infrastructure.database.repositories.execution import ExecutionRepository
from trading_os.infrastructure.database.repositories.market import MarketRepository, NewsRepository
from trading_os.infrastructure.database.repositories.positions import PositionRepository
from trading_os.infrastructure.database.repositories.providers import ProviderRepository
from trading_os.infrastructure.database.repositories.risk import RiskRepository
from trading_os.infrastructure.database.repositories.strategy import StrategyRepository


@dataclass(frozen=True)
class Repositories:
    accounts: AccountRepository
    rules: RuleVersionRepository
    state: SystemStateRepository
    risk: RiskRepository
    positions: PositionRepository
    market: MarketRepository
    news: NewsRepository
    strategy: StrategyRepository
    execution: ExecutionRepository
    events: EventStore
    incidents: IncidentRepository
    providers: ProviderRepository

    @classmethod
    def create(cls, db: Database) -> Repositories:
        return cls(
            accounts=AccountRepository(db),
            rules=RuleVersionRepository(db),
            state=SystemStateRepository(db),
            risk=RiskRepository(db),
            positions=PositionRepository(db),
            market=MarketRepository(db),
            news=NewsRepository(db),
            strategy=StrategyRepository(db),
            execution=ExecutionRepository(db),
            events=EventStore(db),
            incidents=IncidentRepository(db),
            providers=ProviderRepository(db),
        )


__all__ = ["Repositories"]
