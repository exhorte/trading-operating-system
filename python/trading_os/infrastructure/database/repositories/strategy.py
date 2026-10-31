"""Trade intents (what a strategy asked for) and strategy evaluations (what it saw, proposed or not)."""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.strategy.evaluation import StrategyEvaluation
from trading_os.domain.strategy.intent import TradeIntent
from trading_os.infrastructure.database.pool import Database, jsonb


class StrategyRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_intent(self, intent: TradeIntent) -> None:
        await self._db.execute(
            "INSERT INTO trade_intents (intent_id, account_id, strategy_id, strategy_version, symbol, side, "
            "order_type, entry_price, stop_loss, take_profit, created_at, expires_at, rationale, details) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (intent_id) DO NOTHING",
            (
                intent.intent_id,
                intent.account_id,
                intent.strategy_id,
                intent.strategy_version,
                intent.symbol,
                intent.side.value,
                intent.order_type.value,
                intent.entry_price,
                intent.stop_loss,
                intent.take_profit,
                intent.created_at,
                intent.expires_at,
                intent.rationale,
                jsonb(intent.details),
            ),
        )

    async def get_intent(self, intent_id: str) -> TradeIntent | None:
        row = await self._db.fetch_one(
            "SELECT intent_id, account_id, strategy_id, strategy_version, symbol, side, order_type, entry_price, "
            "stop_loss, take_profit, created_at, expires_at, rationale, details FROM trade_intents "
            "WHERE intent_id = %s",
            (intent_id,),
        )
        return TradeIntent.model_validate(dict(row)) if row else None

    async def recent_intents(self, account_id: str, limit: int = 50) -> list[TradeIntent]:
        rows = await self._db.fetch_all(
            "SELECT intent_id, account_id, strategy_id, strategy_version, symbol, side, order_type, entry_price, "
            "stop_loss, take_profit, created_at, expires_at, rationale, details FROM trade_intents "
            "WHERE account_id = %s ORDER BY created_at DESC LIMIT %s",
            (account_id, max(1, min(limit, 500))),
        )
        return [TradeIntent.model_validate(dict(r)) for r in rows]

    async def record_evaluation(self, evaluation: StrategyEvaluation) -> None:
        """Idempotent on (symbol, event_at): a re-detected setup updates its own row."""
        await self._db.execute(
            "INSERT INTO setup_proposals (symbol, event_at, status, stage, detail, side, swept_level_kind, "
            "swept_level_price, entry_price, stop_loss, take_profit, cost_ratio, risk_reward_ratio) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (symbol, event_at) DO UPDATE SET status = EXCLUDED.status, stage = EXCLUDED.stage, "
            "detail = EXCLUDED.detail, side = EXCLUDED.side, swept_level_kind = EXCLUDED.swept_level_kind, "
            "swept_level_price = EXCLUDED.swept_level_price, entry_price = EXCLUDED.entry_price, "
            "stop_loss = EXCLUDED.stop_loss, take_profit = EXCLUDED.take_profit, cost_ratio = EXCLUDED.cost_ratio, "
            "risk_reward_ratio = EXCLUDED.risk_reward_ratio, recorded_at = now()",
            (
                evaluation.symbol,
                evaluation.event_at,
                evaluation.status,
                evaluation.stage,
                evaluation.detail,
                evaluation.side.value if evaluation.side else None,
                evaluation.swept_level_kind,
                evaluation.swept_level_price,
                evaluation.entry_price,
                evaluation.stop_loss,
                evaluation.take_profit,
                evaluation.cost_ratio,
                evaluation.risk_reward_ratio,
            ),
        )

    async def evaluations_since(self, since: datetime) -> list[StrategyEvaluation]:
        rows = await self._db.fetch_all(
            "SELECT symbol, event_at, status, stage, detail, side, swept_level_kind, swept_level_price, entry_price, "
            "stop_loss, take_profit, cost_ratio, risk_reward_ratio FROM setup_proposals WHERE event_at >= %s "
            "ORDER BY event_at DESC",
            (since,),
        )
        return [StrategyEvaluation.model_validate(dict(r)) for r in rows]
