"""``python -m trading_os launcher plan|status`` (ADR 0038, I1): both are **read-only** — they write no file, start nothing, stop nothing."""

from __future__ import annotations

import io
import json
import sys
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
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.observe import Observer
from trading_os.launcher.ports import ProbeError
from trading_os.launcher.registry import ProcessRegistry
from trading_os.shared.time import ManualClock


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Replace the real machine by fakes; the configuration points into ``tmp_path`` so that any write would be visible."""
    config = make_config(tmp_path / "repo" / "04_code")

    def apply(**fakes: object) -> LauncherConfig:
        def make(chosen: LauncherConfig) -> Observer:
            return Observer(
                chosen,
                processes=fakes.get("processes") or FakeProcessTable(),  # type: ignore[arg-type]
                docker=fakes.get("docker") or FakeDocker(container=None),  # type: ignore[arg-type]
                health=fakes.get("health") or FakeHealth(),  # type: ignore[arg-type]
                environment=fakes.get("environment")  # type: ignore[arg-type]
                or FakeEnvironment(existing=[chosen.venv_python, chosen.env_file], tools=["npm"]),
                registry=ProcessRegistry(chosen.registry_path, ManualClock(T0)),
                clock=ManualClock(T0),
            )

        monkeypatch.setattr(launcher_cli, "default_config", lambda: config)
        monkeypatch.setattr(launcher_cli, "make_observer", make)
        return config

    return apply


def everything_running(config: LauncherConfig) -> dict[str, object]:
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
        "health": FakeHealth(core=core_health(), cockpit_status=200),
    }


def test_plan_with_nothing_running_lists_what_a_start_would_do_and_exits_zero(
    install, capsys: pytest.CaptureFixture[str]
) -> None:  # type: ignore[no-untyped-def]
    install()
    assert main(["launcher", "plan"]) == 0
    out = capsys.readouterr().out
    assert "rien n'est lancé" in out.lower()
    for word in ("base", "cœur", "cockpit"):
        assert word in out


def test_plan_with_everything_running_says_there_is_nothing_to_do(install, capsys) -> None:  # type: ignore[no-untyped-def]
    config = install()
    install(**everything_running(config))
    assert main(["launcher", "plan"]) == 0
    assert "rien à faire" in capsys.readouterr().out.lower()


def test_plan_exits_one_when_a_step_is_blocked(install, capsys) -> None:  # type: ignore[no-untyped-def]
    install(docker=FakeDocker(available=False))
    assert main(["launcher", "plan"]) == 1
    assert "bloqué" in capsys.readouterr().out.lower()


def test_plan_json_is_parseable_and_camel_cased(install, capsys) -> None:  # type: ignore[no-untyped-def]
    install()
    assert main(["launcher", "plan", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert [step["stage"] for step in document["plan"]["steps"]] == ["database", "schema", "core", "cockpit"]
    assert "observedAt" in document["observation"]


def test_status_shows_each_component_with_its_state_and_owner(install, capsys) -> None:  # type: ignore[no-untyped-def]
    config = install()
    install(**everything_running(config))
    assert main(["launcher", "status"]) == 0
    out = capsys.readouterr().out
    assert "HEALTHY" in out
    assert "1668" in out and "7900" in out


def test_status_names_a_foreign_process_and_does_not_fail(install, capsys) -> None:  # type: ignore[no-untyped-def]
    install(
        processes=FakeProcessTable(
            [proc(17456, name="node.exe", command_line=r"node C:\Ebrain\jobdom\04_code\node_modules\next\x.js")],
            [listener(3000, 17456)],
        ),
        health=FakeHealth(cockpit_status=200),
    )
    assert main(["launcher", "status"]) == 0
    out = capsys.readouterr().out
    assert "FOREIGN" in out
    assert "17456" in out


def test_neither_command_writes_anything(install, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    install()
    before = sorted(path for path in tmp_path.rglob("*"))
    main(["launcher", "plan"])
    main(["launcher", "status"])
    assert sorted(path for path in tmp_path.rglob("*")) == before


def test_an_observation_that_cannot_be_read_is_reported_and_exits_two(
    install, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    class Broken:
        def processes(self):  # type: ignore[no-untyped-def]
            raise ProbeError("PowerShell did not answer")

        def listeners(self, ports):  # type: ignore[no-untyped-def]
            raise ProbeError("PowerShell did not answer")

    install(processes=Broken())
    assert main(["launcher", "status"]) == 2
    assert "PowerShell did not answer" in capsys.readouterr().err


def test_a_redirected_output_is_utf_8_not_the_windows_code_page(
    install,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    """Redirected, a Windows Python writes cp1252 — « état » would reach a log or a wrapper as bytes nobody decodes as UTF-8."""
    install()
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    assert main(["launcher", "status"]) == 0
    sys.stdout.flush()
    assert "état observé" in raw.getvalue().decode("utf-8")


def test_the_command_needs_a_subcommand() -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["launcher"])
    assert stopped.value.code == 2
