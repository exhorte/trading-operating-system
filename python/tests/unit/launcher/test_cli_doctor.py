"""``python -m trading_os launcher doctor`` (ADR 0039, § 6): read-only like ``plan`` and ``status``. It writes no file, takes no lock, removes no stale
lock, starts nothing, stops nothing. Exit codes follow the ones already in place: 0 nothing is wrong · 1 a problem · 2 the machine could not be observed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.launcher.support import (
    T0,
    FakeDocker,
    FakeEnvironment,
    FakeHealth,
    FakeProcessTable,
    container,
    core_health,
    listener,
    make_config,
    proc,
)
from trading_os.cli.main import main
from trading_os.launcher import cli as launcher_cli
from trading_os.launcher.model import LauncherConfig, Mt5WorkersFacts
from trading_os.launcher.observe import Observer
from trading_os.launcher.ports import ProbeError
from trading_os.launcher.registry import ProcessRegistry
from trading_os.shared.time import ManualClock


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    """The machine is replaced by fakes; the configuration points into ``tmp_path`` so that any write would be visible."""
    config = make_config(tmp_path / "repo" / "04_code")

    def apply(*, table: FakeProcessTable | None = None, **fakes: object) -> LauncherConfig:
        chosen_table = table or fakes.get("processes") or FakeProcessTable()

        def make(chosen: LauncherConfig) -> Observer:
            return Observer(
                chosen,
                processes=chosen_table,  # type: ignore[arg-type]
                docker=fakes.get("docker") or FakeDocker(container=None),  # type: ignore[arg-type]
                health=fakes.get("health") or FakeHealth(),  # type: ignore[arg-type]
                environment=fakes.get("environment")  # type: ignore[arg-type]
                or FakeEnvironment(existing=[chosen.venv_python, chosen.env_file], tools=["npm"]),
                registry=ProcessRegistry(chosen.registry_path, ManualClock(T0)),
                clock=ManualClock(T0),
            )

        monkeypatch.setattr(launcher_cli, "default_config", lambda: config)
        monkeypatch.setattr(launcher_cli, "make_observer", make)
        monkeypatch.setattr(launcher_cli, "make_process_table", lambda: chosen_table)
        # the diagnosis of MetaTrader has its own tests (tests/unit/launcher/mt5): here it must not look at the real machine
        monkeypatch.setattr(launcher_cli, "gather_mt5_facts", lambda config: fakes.get("mt5"))
        return config

    return apply


def everything_running(config: LauncherConfig, **health: object) -> dict[str, object]:
    return {
        "processes": FakeProcessTable(
            [
                proc(
                    1668, command_line=f'"{config.repo_root}\\python\\.venv\\Scripts\\python.exe" -m trading_os serve'
                ),
                proc(7900, name="node.exe", command_line=f"node {config.repo_root}\\node_modules\\next\\dist\\x.js"),
            ],
            [listener(8000, 1668), listener(9765, 1668), listener(3000, 7900)],
        ),
        "docker": FakeDocker(container=container()),
        "health": FakeHealth(core=core_health(**health), cockpit_status=200),
    }


def test_a_healthy_machine_exits_zero_and_says_it_is_read_only(install, capsys) -> None:  # type: ignore[no-untyped-def]
    config = install()
    install(**everything_running(config))
    assert main(["launcher", "doctor"]) == 0
    out = capsys.readouterr().out
    assert "lecture seule" in out
    assert "aucun problème" in out.lower()


def test_a_problem_exits_one_and_gives_the_action(install, capsys) -> None:  # type: ignore[no-untyped-def]
    install(docker=FakeDocker(available=False))
    assert main(["launcher", "doctor"]) == 1
    out = capsys.readouterr().out
    assert "Docker" in out
    assert "→ action" in out


def test_a_machine_that_cannot_be_observed_exits_two_and_says_why(install, capsys) -> None:  # type: ignore[no-untyped-def]
    class Broken:
        def processes(self):  # type: ignore[no-untyped-def]
            raise ProbeError("PowerShell did not answer")

        def listeners(self, ports):  # type: ignore[no-untyped-def]
            raise ProbeError("PowerShell did not answer")

    install(processes=Broken())
    assert main(["launcher", "doctor"]) == 2
    assert "PowerShell did not answer" in capsys.readouterr().err


def test_the_core_view_comes_from_the_health_the_core_reports(install, capsys) -> None:  # type: ignore[no-untyped-def]
    config = install()
    install(
        **everything_running(config, agents_connected=0, mt5_workers=Mt5WorkersFacts(spawned=15, ended=14, alive=1))
    )
    assert main(["launcher", "doctor"]) == 0
    out = capsys.readouterr().out
    assert "aucun agent EA connecté" in out
    assert "worker" in out.lower()


def test_json_is_parseable_and_carries_the_verdict(install, capsys) -> None:  # type: ignore[no-untyped-def]
    config = install()
    install(**everything_running(config))
    assert main(["launcher", "doctor", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True
    assert {check["family"] for check in document["checks"]} >= {
        "environment",
        "components",
        "launcher",
        "core",
        "metatrader",
    }


def test_it_writes_nothing_at_all(install, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    config = install()
    install(**everything_running(config))
    before = sorted(tmp_path.rglob("*"))
    main(["launcher", "doctor"])
    main(["launcher", "doctor", "--json"])
    assert sorted(tmp_path.rglob("*")) == before


def test_a_stale_lock_is_reported_and_left_exactly_where_it_is(install, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    config = install()
    install(**everything_running(config))
    config.lock_path.parent.mkdir(parents=True)
    content = json.dumps({"pid": 999, "createdAt": "2026-11-06T09:00:00Z"})
    config.lock_path.write_text(content, encoding="utf-8")
    assert main(["launcher", "doctor"]) == 0  # a stale lock is a warning, not a problem
    out = capsys.readouterr().out
    assert "ATTENTION" in out
    assert "périmé" in out
    assert config.lock_path.read_text(encoding="utf-8") == content  # not removed, not rewritten


def test_a_lock_held_by_a_live_launcher_is_reported_as_busy_and_left_alone(install, capsys) -> None:  # type: ignore[no-untyped-def]
    config = install()
    running = everything_running(config)
    table: FakeProcessTable = running["processes"]  # type: ignore[assignment]
    table._processes.append(proc(4242))  # created at T0, as the lock below says
    install(**running)
    config.lock_path.parent.mkdir(parents=True)
    content = json.dumps({"pid": 4242, "createdAt": "2026-11-06T15:30:00Z"})
    config.lock_path.write_text(content, encoding="utf-8")
    assert main(["launcher", "doctor"]) == 0
    out = capsys.readouterr().out
    assert "4242" in out
    assert config.lock_path.read_text(encoding="utf-8") == content


def test_the_command_is_registered_with_a_help_text() -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["launcher", "doctor", "--help"])
    assert stopped.value.code == 0
