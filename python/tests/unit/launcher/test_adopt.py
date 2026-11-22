"""Adopting (ADR 0038, § 3): a person's explicit gesture that turns a *recognized* process — one started by hand, carrying this repository's
signature — into one the launcher owns, so that ``stop`` may end it. Everything else is refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.launcher.world import World
from trading_os.launcher.adopt import adopt
from trading_os.launcher.events import EventType
from trading_os.launcher.model import Component, Ownership, StopStatus


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def run(world: World, component: Component):  # type: ignore[no-untyped-def]
    return adopt(
        component,
        observer=world.observer(),
        processes=world.table,
        registry=world.registry,
        events=world.events,
        clock=world.clock,
        correlation_id="adopt-1",
    )


def test_a_recognized_core_is_adopted_with_its_identity(world: World) -> None:
    world.run_everything()
    outcome = run(world, Component.CORE)
    assert outcome.adopted
    (entry,) = world.registry.load().owned
    assert (entry.component, entry.pid) == (Component.CORE, world.core_pid)
    assert entry.created_at == next(p for p in world.table.processes() if p.pid == world.core_pid).created_at
    assert world.observer().observe().component(Component.CORE).ownership is Ownership.OWNED
    assert EventType.LAUNCHER_PROCESS_ADOPTED in {event.type for event in world.events.read()}


def test_after_adoption_stop_may_end_it(world: World) -> None:
    world.run_everything()
    run(world, Component.CORE)
    report = world.stopper().stop()
    assert report.outcome(Component.CORE).status is StopStatus.STOPPED
    assert ("stop.request", world.core_pid) in world.calls


def test_a_process_the_launcher_already_owns_is_not_adopted_again(world: World) -> None:
    world.run_everything()
    run(world, Component.CORE)
    again = run(world, Component.CORE)
    assert not again.adopted
    assert "déjà" in again.detail


def test_a_foreign_process_is_refused(world: World) -> None:
    stranger = world.add_process(900, r'"C:\other\python.exe" -m something_else')
    world.listen(world.config.api_port, stranger.pid)
    outcome = run(world, Component.CORE)
    assert not outcome.adopted
    assert world.registry.load().owned == ()


def test_nothing_running_is_refused(world: World) -> None:
    outcome = run(world, Component.CORE)
    assert not outcome.adopted
    assert not world.registry.path.exists()


def test_the_database_is_a_container_and_cannot_be_adopted(world: World) -> None:
    world.run_everything()
    outcome = run(world, Component.DATABASE)
    assert not outcome.adopted
    assert "conteneur" in outcome.detail
