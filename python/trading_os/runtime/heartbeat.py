"""The core's own heartbeat: ``system.heartbeat`` every couple of seconds.

Two readers depend on it. The cockpit, which treats a missing heartbeat for 8 s as « stale » and takes no decision on stale
data (``docs/architecture`` § 9); and the supervisor, for which the beat is the proof that the event loop is turning at all.
It carries a sequence number so a client can tell a missed beat from a duplicate.
"""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.events import SystemHeartbeat
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock


class Heartbeat:
    def __init__(self, *, events: EventDispatcher, clock: Clock) -> None:
        self._events = events
        self._clock = clock
        self.started_at: datetime = clock.now()
        self.seq = 0
        self.last_beat_at: datetime | None = None

    def uptime_seconds(self) -> float:
        return (self._clock.now() - self.started_at).total_seconds()

    async def beat(self) -> None:
        self.seq += 1
        self.last_beat_at = self._clock.now()
        await self._events.publish(SystemHeartbeat(seq=self.seq, uptime_seconds=round(self.uptime_seconds(), 1)))
