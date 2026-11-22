"""``launcher start | stop | adopt`` (ADR 0038, I2) through the command line, on a simulated machine: exit codes, what is printed, the lock, and that a
dry run changes nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.launcher.support import T0
from tests.unit.launcher.world import World
from trading_os.cli.main import main
from trading_os.launcher import cli as launcher_cli
from trading_os.launcher.model import Component, ContainerInfo, OwnedProcess


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    w = World(tmp_path)
    w.container = ContainerInfo(name=w.config.container_name, status="exited", health=None, host_ports=())
    runtime = w.runtime()
    monkeypatch.setattr(launcher_cli, "default_config", lambda: w.config)
    monkeypatch.setattr(launcher_cli, "make_runtime", lambda config: runtime)
    return w


def test_start_brings_the_application_up_and_says_nothing_was_armed(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["launcher", "start"]) == 0
    out = capsys.readouterr().out
    assert "Démarrage de Trading OS" in out
    assert "fait" in out
    assert "Rien n'est armé" in out
    assert world.core_up and world.cockpit_up
    assert not world.config.lock_path.exists(), "the lock is released"


def test_start_twice_changes_nothing_the_second_time(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    main(["launcher", "start"])
    before = len(world.calls)
    assert main(["launcher", "start"]) == 0
    assert len(world.calls) == before
    assert "déjà en place" in capsys.readouterr().out


def test_start_exits_one_and_names_the_failure(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.db_never_healthy = True
    assert main(["launcher", "start"]) == 1
    assert "ÉCHEC" in capsys.readouterr().out


def test_start_is_refused_while_another_launcher_runs(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    other = world.add_process(900, "python -m trading_os launcher")
    world.config.lock_path.parent.mkdir(parents=True, exist_ok=True)
    world.config.lock_path.write_text(
        json.dumps({"pid": 900, "createdAt": other.created_at.isoformat() if other.created_at else ""}),
        encoding="utf-8",
    )
    assert main(["launcher", "start"]) == 1
    assert "autre lanceur" in capsys.readouterr().err
    assert not world.did("spawn")


def test_start_json_is_the_report(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["launcher", "start", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert [item["stage"] for item in document["outcomes"]] == ["database", "schema", "core", "cockpit"]


def test_stop_ends_what_was_started_and_leaves_metatrader_alone(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["launcher", "start"])
    terminal = world.add_process(901, r'"C:\Program Files\MetaTrader 5\terminal64.exe"', name="terminal64.exe")
    capsys.readouterr()
    assert main(["launcher", "stop"]) == 0
    out = capsys.readouterr().out
    assert "arrêté" in out
    assert "MetaTrader 5 et son agent ne sont pas touchés" in out
    assert not world.core_up and not world.cockpit_up
    assert world.alive(terminal.pid)


def test_a_dry_run_stops_nothing_and_writes_nothing(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    main(["launcher", "start"])
    capsys.readouterr()
    calls = len(world.calls)
    assert main(["launcher", "stop", "--dry-run"]) == 0
    assert "simulation" in capsys.readouterr().out
    assert len(world.calls) == calls
    assert world.core_up and world.cockpit_up
    assert not world.config.lock_path.exists()


def test_stop_exits_one_when_something_cannot_be_ended(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    main(["launcher", "start"])
    world.kill_fails = True
    assert main(["launcher", "stop"]) == 1
    assert "ÉCHEC" in capsys.readouterr().out


def test_adopt_makes_a_hand_started_core_stoppable(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.run_everything()
    assert main(["launcher", "adopt", "core"]) == 0
    assert "adopté" in capsys.readouterr().out
    assert [item.component for item in world.registry.load().owned] == [Component.CORE]
    assert main(["launcher", "adopt", "core"]) == 1
    assert "refusé" in capsys.readouterr().out


def test_adopt_refuses_when_nothing_runs(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["launcher", "adopt", "cockpit"]) == 1
    assert "refusé" in capsys.readouterr().out


def test_adopt_only_knows_the_three_components() -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["launcher", "adopt", "metatrader"])
    assert stopped.value.code == 2


def test_the_registry_entry_written_by_a_start_survives_between_commands(world: World) -> None:
    main(["launcher", "start"])
    entries = world.registry.load().owned
    assert {entry.component for entry in entries} == {Component.CORE, Component.COCKPIT}
    assert all(isinstance(entry, OwnedProcess) and entry.started_at >= T0 for entry in entries)
