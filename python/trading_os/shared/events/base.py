"""Base class of every event. One pydantic model per event is the single source of truth: the same model
feeds the audit table, the WebSocket frame and (through OpenAPI/JSON Schema) the cockpit's TypeScript types."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from trading_os.shared.ids import new_id
from trading_os.shared.time import iso, utcnow

EVENT_REGISTRY: dict[str, type[Event]] = {}

_ENVELOPE_FIELDS = {"id", "occurred_at", "account_id", "correlation_id"}


class Event(BaseModel):
    """Frozen, camelCase on the wire. Subclasses set ``wire_type`` (dotted, stable) and add payload fields.

    ``persist`` — appended to the audit table. High-rate telemetry (ticks, heartbeats, account snapshots) sets it
    to False: it is broadcast to the cockpit but would only bloat the audit trail.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, alias_generator=to_camel)

    wire_type: ClassVar[str] = ""
    persist: ClassVar[bool] = True

    id: str = Field(default_factory=lambda: new_id("evt"))
    occurred_at: datetime = Field(default_factory=utcnow)
    account_id: str | None = None
    correlation_id: str | None = None

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        wire_type = cls.__dict__.get("wire_type")
        if wire_type:
            if wire_type in EVENT_REGISTRY:
                raise TypeError(f"duplicate event wire type {wire_type!r}")
            EVENT_REGISTRY[wire_type] = cls

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude=_ENVELOPE_FIELDS)

    def to_wire(self) -> dict[str, Any]:
        return {
            "type": self.wire_type,
            "id": self.id,
            "occurredAt": iso(self.occurred_at),
            "accountId": self.account_id,
            "correlationId": self.correlation_id,
            "payload": self.payload(),
        }
