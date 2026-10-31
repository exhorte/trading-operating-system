"""Scheduler: isolated, measured, non-overlapping periodic jobs — and the heartbeat the supervisor reads."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from trading_os.domain.events import SystemHeartbeat
from trading_os.runtime.heartbeat import Heartbeat
from trading_os.runtime.scheduler import Scheduler
from trading_os.shared.errors import Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import ManualClock


class Counter:
    def __init__(self) -> None:
        self.calls = 0

    async def ok(self) -> None:
        self.calls += 1


async def test_a_job_runs_and_is_measured() -> None:
    clock, counter = ManualClock(), Counter()
    scheduler = Scheduler(clock)
    scheduler.add("tick", counter.ok, interval_s=1.0)
    await scheduler.run_once("tick")
    stats = scheduler.stat("tick")
    assert stats is not None and counter.calls == 1 and stats.runs == 1 and stats.failures == 0
    assert stats.last_success_at == clock.now() and stats.last_duration_ms is not None and stats.last_error is None


async def test_a_failing_job_is_recorded_and_never_stops_the_others() -> None:
    scheduler, counter = Scheduler(ManualClock()), Counter()

    async def bug() -> None:
        raise RuntimeError("boom")

    scheduler.add("bug", bug, interval_s=1.0, critical=True)
    scheduler.add("fine", counter.ok, interval_s=1.0)
    await scheduler.run_once("bug")
    await scheduler.run_once("fine")
    bad, good = scheduler.stat("bug"), scheduler.stat("fine")
    assert bad is not None and good is not None
    assert (bad.failures, bad.consecutive_failures, bad.unexpected_streak) == (1, 1, 1)
    assert bad.last_error == "RuntimeError: boom" and good.failures == 0 and counter.calls == 1


async def test_a_handled_condition_is_not_an_unexpected_failure() -> None:
    scheduler = Scheduler(ManualClock())

    async def down() -> None:
        raise Unavailable("database unavailable", code="database_unavailable")

    scheduler.add("poll", down, interval_s=1.0, critical=True)
    for _ in range(6):
        await scheduler.run_once("poll")
    stats = scheduler.stat("poll")
    assert stats is not None and stats.consecutive_failures == 6 and stats.unexpected_streak == 0
    assert stats.last_error == "database_unavailable: database unavailable"  # the system describing what it handles


async def test_a_bug_streak_counts_and_a_success_ends_it() -> None:
    scheduler, state = Scheduler(ManualClock()), {"fail": True}

    async def sometimes() -> None:
        if state["fail"]:
            raise ValueError("bad")

    scheduler.add("job", sometimes, interval_s=1.0)
    for _ in range(3):
        await scheduler.run_once("job")
    stats = scheduler.stat("job")
    assert stats is not None and stats.unexpected_streak == 3
    state["fail"] = False
    await scheduler.run_once("job")
    assert stats.unexpected_streak == 0 and stats.consecutive_failures == 0 and stats.failures == 3


async def test_a_job_that_hangs_is_cut_off_at_its_timeout() -> None:
    scheduler = Scheduler(ManualClock())

    async def hang() -> None:
        await asyncio.sleep(10)

    scheduler.add("hang", hang, interval_s=1.0, timeout_s=0.05)
    await scheduler.run_once("hang")
    stats = scheduler.stat("hang")
    assert (
        stats is not None and stats.timeouts == 1 and stats.last_error == "timed out after 0.05s" and not stats.running
    )


async def test_the_loop_runs_periodically_without_overlapping_itself() -> None:
    running = {"now": 0, "max": 0, "calls": 0}

    async def slow() -> None:
        running["now"] += 1
        running["max"] = max(running["max"], running["now"])
        running["calls"] += 1
        await asyncio.sleep(0.03)
        running["now"] -= 1

    scheduler = Scheduler(ManualClock())
    scheduler.add("slow", slow, interval_s=0.01)  # the job is slower than its own interval
    await scheduler.start()
    await asyncio.sleep(0.25)
    await scheduler.stop()
    assert running["calls"] >= 3 and running["max"] == 1  # it delays itself, it does not pile up


async def test_stop_cancels_every_job_and_a_late_job_can_still_be_added() -> None:
    first, second = Counter(), Counter()
    scheduler = Scheduler(ManualClock())
    scheduler.add("a", first.ok, interval_s=0.01)
    await scheduler.start()
    scheduler.add("b", second.ok, interval_s=0.01)  # registered while running: starts at once
    await asyncio.sleep(0.1)
    await scheduler.stop()
    seen = (first.calls, second.calls)
    await asyncio.sleep(0.05)
    assert seen[0] >= 2 and seen[1] >= 2 and (first.calls, second.calls) == seen  # nothing runs after stop


async def test_duplicate_names_are_refused() -> None:
    scheduler = Scheduler(ManualClock())
    scheduler.add("a", Counter().ok, interval_s=1.0)
    with pytest.raises(ValueError):
        scheduler.add("a", Counter().ok, interval_s=1.0)


async def test_a_job_that_has_not_finished_for_a_while_is_overdue() -> None:
    clock, counter = ManualClock(), Counter()
    scheduler = Scheduler(clock)
    scheduler.add("fast", counter.ok, interval_s=1.0)
    scheduler.add("slow", counter.ok, interval_s=60.0)
    await scheduler.run_once("fast")
    await scheduler.run_once("slow")
    clock.advance(seconds=9)
    assert scheduler.overdue(clock.now()) == []  # even a 1 s job gets 10 s of allowance
    clock.advance(seconds=2)
    assert [s.name for s in scheduler.overdue(clock.now())] == ["fast"]
    clock.advance(seconds=200)
    assert {s.name for s in scheduler.overdue(clock.now())} == {"fast", "slow"}


async def test_a_job_registered_but_never_finished_is_overdue_too() -> None:
    clock = ManualClock()
    scheduler = Scheduler(clock)
    scheduler.add("never", Counter().ok, interval_s=1.0)
    clock.advance(seconds=30)
    assert [s.name for s in scheduler.overdue(clock.now())] == ["never"]


async def test_the_heartbeat_counts_and_reports_uptime() -> None:
    clock, events = ManualClock(), EventDispatcher()
    seen: list[SystemHeartbeat] = []
    events.subscribe(SystemHeartbeat, seen.append)
    heartbeat = Heartbeat(events=events, clock=clock)
    assert heartbeat.last_beat_at is None
    await heartbeat.beat()
    clock.advance(seconds=2)
    await heartbeat.beat()
    assert [(e.seq, e.uptime_seconds) for e in seen] == [(1, 0.0), (2, 2.0)]
    assert heartbeat.last_beat_at == clock.now() and heartbeat.uptime_seconds() == timedelta(seconds=2).total_seconds()
    assert not SystemHeartbeat.persist  # telemetry: broadcast, never appended to the audit trail
