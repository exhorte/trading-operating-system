"""Idempotency (ADR 0010): a command replayed under the same ``command_id`` returns the result already recorded for it —
it never executes a second time and never produces a second position.

The store is the database (``execution_commands.command_id`` is the primary key); this module is the pure rule over
what the store answers. Same id + same content → replay the recorded command. Same id + *different* content → conflict
(refused): an id is a promise about one specific order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from trading_os.domain.execution.commands import ExecutionCommand, ExecutionRequest

# Fields that define *what* is asked. Timestamps are excluded: a client replaying the same order a second later is
# the same order.
_FINGERPRINT_FIELDS = (
    "account_id",
    "kind",
    "symbol",
    "side",
    "order_type",
    "volume",
    "price",
    "stop_loss",
    "take_profit",
    "strategy_id",
    "strategy_version",
    "risk_decision_id",
    "position_id",
    "order_id",
)


def request_fingerprint(request: ExecutionRequest) -> str:
    data = request.model_dump(mode="json")
    canonical = json.dumps({name: data[name] for name in _FINGERPRINT_FIELDS}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReplayOutcome(StrEnum):
    NEW = "new"
    REPLAY = "replay"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class ReplayDecision:
    outcome: ReplayOutcome
    existing: ExecutionCommand | None = None


def check_replay(existing: ExecutionCommand | None, request: ExecutionRequest) -> ReplayDecision:
    if existing is None:
        return ReplayDecision(ReplayOutcome.NEW)
    if existing.fingerprint == request_fingerprint(request):
        return ReplayDecision(ReplayOutcome.REPLAY, existing)
    return ReplayDecision(ReplayOutcome.CONFLICT, existing)
