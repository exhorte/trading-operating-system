"""The scheduler: named periodic jobs, each isolated from the others and measured.

* **One task per job, sequential within a job.** A job never overlaps itself — a slow poll delays its own next run, it does
  not pile up behind it — and a job that raises, or hangs past its timeout, never touches another job.
* **Everything is measured**, because the supervisor judges the core from it: runs, failures, the streak of consecutive
  failures, how long the last run took, when it last *finished*. A job that has not finished within a few of its intervals
  is ``overdue`` — the core is not keeping up, which for a trading system is a finding in its own right.
* **Expected failures are told from unexpected ones.** A ``TradingOsError`` (database unavailable, terminal unreadable …) is
  the system describing a condition it handles; any other exception is a bug. The streak of *unexpected* failures of a
  ``critical`` job is what the supervisor treats as « critical error » (HALT) — a database outage is not.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from trading_os.shared.errors import TradingOsError
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

Job = Callable[[], Awaitable[None]]
MIN_OVERDUE_S = 10.0  # even a fast job gets this long before it counts as stalled
LOG_EVERY = 20  # an unexpected failure that repeats is logged with its traceback on the 1st, 20th, 40th … occurrence


@dataclass
class JobStats:
    name: str
    interval_s: float
    timeout_s: float | None
    critical: bool
    runs: int = 0
    failures: int = 0
    timeouts: int = 0
    consecutive_failures: int = 0
    unexpected_streak: int = 0  # consecutive failures that were NOT a TradingOsError
    running: bool = False
    registered_at: datetime | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_success_at: datetime | None = None
    last_duration_ms: float | None = None
    last_error: str | None = None

    def overdue(self, now: datetime, factor: float = 3.0) -> bool:
        """Has not finished a run for ``factor`` intervals (and at least ``MIN_OVERDUE_S``): hung or starved."""
        reference = self.last_finished_at or self.registered_at
        if reference is None:
            return False
        allowance = max(self.interval_s * factor, MIN_OVERDUE_S, (self.timeout_s or 0.0) + self.interval_s)
        return (now - reference).total_seconds() > allowance


class Scheduler:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._jobs: dict[str, tuple[Job, JobStats, float]] = {}  # name → (fn, stats, initial delay)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._started = False

    # ------------------------------------------------------------------------------------------ registration
    def add(
        self,
        name: str,
        fn: Job,
        *,
        interval_s: float,
        timeout_s: float | None = None,
        critical: bool = False,
        initial_delay_s: float = 0.0,
    ) -> None:
        if name in self._jobs:
            raise ValueError(f"job {name!r} is already registered")
        stats = JobStats(
            name=name, interval_s=interval_s, timeout_s=timeout_s, critical=critical, registered_at=self._clock.now()
        )
        self._jobs[name] = (fn, stats, initial_delay_s)
        if self._started:
            self._tasks[name] = asyncio.create_task(self._loop(name), name=f"job:{name}")

    # ------------------------------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for name in self._jobs:
            self._tasks[name] = asyncio.create_task(self._loop(name), name=f"job:{name}")

    async def stop(self) -> None:
        self._started = False
        tasks, self._tasks = list(self._tasks.values()), {}
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # ------------------------------------------------------------------------------------------ reading
    def stats(self) -> list[JobStats]:
        return [stats for _, stats, _ in self._jobs.values()]

    def stat(self, name: str) -> JobStats | None:
        entry = self._jobs.get(name)
        return entry[1] if entry else None

    def overdue(self, now: datetime, factor: float = 3.0) -> list[JobStats]:
        return [s for s in self.stats() if s.overdue(now, factor)]

    # ------------------------------------------------------------------------------------------ running
    async def run_once(self, name: str) -> None:
        """One iteration, inline — what the loop does, without the loop (tests; forcing a cycle)."""
        await self._iterate(name)

    async def _loop(self, name: str) -> None:
        _, stats, initial_delay = self._jobs[name]
        if initial_delay > 0:
            await asyncio.sleep(initial_delay)
        while True:
            started = time.monotonic()
            await self._iterate(name)
            await asyncio.sleep(max(0.0, stats.interval_s - (time.monotonic() - started)))

    async def _iterate(self, name: str) -> None:
        fn, stats, _ = self._jobs[name]
        stats.running = True
        stats.last_started_at = self._clock.now()
        started = time.monotonic()
        error: str | None = None
        unexpected = False
        try:
            if stats.timeout_s is not None:
                await asyncio.wait_for(fn(), timeout=stats.timeout_s)
            else:
                await fn()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            stats.timeouts += 1
            error = f"timed out after {stats.timeout_s:g}s"
        except TradingOsError as failure:
            error = f"{failure.code}: {failure.safe_message}"
        except Exception as failure:
            unexpected = True
            error = f"{type(failure).__name__}: {failure}"
            if stats.unexpected_streak % LOG_EVERY == 0:
                logger.exception("job %s failed unexpectedly", name)
        finally:
            stats.running = False
            stats.runs += 1
            stats.last_duration_ms = (time.monotonic() - started) * 1000
            stats.last_finished_at = self._clock.now()
        if error is None:
            stats.consecutive_failures = 0
            stats.unexpected_streak = 0
            stats.last_success_at = stats.last_finished_at
            stats.last_error = None
        else:
            stats.failures += 1
            stats.consecutive_failures += 1
            stats.unexpected_streak = stats.unexpected_streak + 1 if unexpected else 0
            stats.last_error = error
            if not unexpected:
                logger.debug("job %s: %s", name, error)
