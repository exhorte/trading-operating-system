"""``scripts/TradingOS.Docker.ps1`` and its call from ``TradingOS.bat`` (ADR 0038, decision A11 — « Docker Desktop éteint » — taken the other way by Exhorte on
2026-11-22: « le lancer »).

The script starts Docker Desktop when the engine does not answer, waits for the engine, and does nothing else. The tests run it for real under PowerShell,
against a *fake* ``docker`` (it answers once a marker file exists) and a *fake* Docker Desktop (it creates that marker): the real Docker, the real Docker
Desktop and the real launcher are never reached.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import trading_os

REPO = Path(trading_os.__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "TradingOS.Docker.ps1"
WINDOWS_POWERSHELL = shutil.which("powershell")  # 5.1: reads a script without a BOM as cp1252 — where accents break
POWERSHELL_7 = shutil.which("pwsh")
SHELLS = [path for path in (WINDOWS_POWERSHELL, POWERSHELL_7) if path]
PREFERRED = POWERSHELL_7 or WINDOWS_POWERSHELL

pytestmark = pytest.mark.skipif(sys.platform != "win32" or not SHELLS, reason="a Windows PowerShell script")

FAKE = """\
import json
import os
import sys

who = sys.argv[1]
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"who": who, "argv": sys.argv[2:]}) + "\\n")
if who == "desktop":
    if os.environ.get("FAKE_DESKTOP_SILENT") != "1":
        open(os.environ["FAKE_MARKER"], "w").close()  # Docker Desktop is up: the engine answers from now on
    sys.exit(0)
sys.exit(0 if os.path.exists(os.environ["FAKE_MARKER"]) else 1)  # the fake ``docker``
"""


@dataclass
class World:
    root: Path
    log: Path
    marker: Path
    docker: Path
    desktop: Path

    def calls(self) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def who(self) -> list[str]:
        return [str(call["who"]) for call in self.calls()]


@pytest.fixture
def world(tmp_path: Path) -> World:
    root = tmp_path / "Docker fake"  # a path with a space, as the real ones have
    root.mkdir()
    (root / "fake.py").write_text(FAKE, encoding="utf-8")
    docker = root / "docker.cmd"
    docker.write_text(f'@"{sys.executable}" "{root / "fake.py"}" docker %*\r\n', encoding="utf-8")
    desktop = root / "Docker Desktop.cmd"
    desktop.write_text(f'@"{sys.executable}" "{root / "fake.py"}" desktop %*\r\n', encoding="utf-8")
    return World(root=root, log=tmp_path / "fake.jsonl", marker=tmp_path / "engine.up", docker=docker, desktop=desktop)


def run_script(
    world: World,
    *,
    shell: str | None = None,
    silent_desktop: bool = False,
    timeout_s: int = 8,
    desktop: Path | None = None,
    process_name: str = "NoSuchProcessForTests",
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update({"FAKE_LOG": str(world.log), "FAKE_MARKER": str(world.marker), "PYTHONUTF8": "1"})
    if silent_desktop:
        env["FAKE_DESKTOP_SILENT"] = "1"
    command = [
        shell or PREFERRED or "",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-DockerCommand",
        str(world.docker),
        "-DesktopPath",
        str(desktop or world.desktop),
        "-ProcessName",
        process_name,
        "-TimeoutSeconds",
        str(timeout_s),
        "-PollSeconds",
        "1",
    ]
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, check=False)


def test_the_script_exists_and_carries_a_byte_order_mark_so_that_windows_powershell_reads_its_accents() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_when_the_engine_already_answers_nothing_is_started(world: World) -> None:
    world.marker.write_text("up", encoding="utf-8")
    result = run_script(world)
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.who() == ["docker"]  # one look at the engine, no Docker Desktop


@pytest.mark.parametrize("shell", SHELLS)
def test_when_the_engine_is_down_it_starts_docker_desktop_once_and_waits_for_the_engine(
    world: World, shell: str
) -> None:
    result = run_script(world, shell=shell)
    assert result.returncode == 0, result.stdout + result.stderr
    who = world.who()
    assert who.count("desktop") == 1 and who[0] == "docker" and who[-1] == "docker"
    assert all(
        call["argv"] == ["info"] for call in world.calls() if call["who"] == "docker"
    )  # it only ever asks « docker info »
    assert (
        "démarrage" in result.stdout and "prêt" in result.stdout
    )  # accents survive a redirected output, on 5.1 as on 7


def test_an_engine_that_never_answers_is_a_failure_after_the_delay_not_a_hang(world: World) -> None:
    result = run_script(world, silent_desktop=True, timeout_s=3)
    assert result.returncode == 1
    assert world.who().count("desktop") == 1
    assert "3 s" in result.stdout + result.stderr and "Docker" in result.stdout + result.stderr


def test_a_missing_docker_desktop_is_named_and_nothing_is_started(world: World) -> None:
    missing = world.root / "nowhere" / "Docker Desktop.exe"
    result = run_script(world, desktop=missing)
    assert result.returncode == 1
    assert "introuvable" in result.stdout + result.stderr and "Docker Desktop.exe" in result.stdout + result.stderr
    assert (
        "desktop" not in world.who()
    )  # an explicit path is never replaced by a guess: the real Docker Desktop is not touched


def test_a_docker_desktop_that_is_already_running_is_waited_for_never_started_a_second_time(world: World) -> None:
    shell = PREFERRED or ""
    running = Path(shell).stem  # the shell that runs the script is a running process of that name
    result = run_script(world, timeout_s=3, process_name=running)
    assert result.returncode == 1  # its engine never answered (no marker)
    assert "desktop" not in world.who()
    assert "lancé" in result.stdout and "répond pas" in result.stdout


# ------------------------------------------------------------------------------------------------ the batch file calls it


BAT_STUB = """\
import json
import os
import sys

with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:]}) + "\\n")
print("stub: " + " ".join(sys.argv[1:]))
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""

DOCKER_STUB_PS1 = """\
$line = '{"argv": ["docker-script", "' + ($args -join ' ') + '"]}'
Add-Content -LiteralPath $env:STUB_LOG -Value $line
exit ([int]$env:STUB_DOCKER_EXIT)
"""


def make_bat_tree(tmp_path: Path, *, with_docker_script: bool = True) -> Path:
    root = tmp_path / "Trading OS" / "04 code"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "TradingOS.Launcher.ps1", root / "scripts")
    shutil.copy(REPO / "TradingOS.bat", root)
    if (
        with_docker_script
    ):  # a *stub* of the script: the real one is tested above, and must not touch the real Docker here
        (root / "scripts" / "TradingOS.Docker.ps1").write_text(DOCKER_STUB_PS1, encoding="utf-8")
    stub = root / "python" / "trading_os"
    stub.mkdir(parents=True)
    (stub / "__main__.py").write_text(BAT_STUB, encoding="utf-8")
    return root


def run_bat(
    root: Path, log: Path, *args: str, docker_exit: int = 0, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("TRADINGOS_NODOCKERSTART", None)
    env.update(
        {
            "STUB_LOG": str(log),
            "STUB_DOCKER_EXIT": str(docker_exit),
            "PYTHONUTF8": "1",
            "TRADINGOS_NOPAUSE": "1",
            **(extra_env or {}),
        }
    )
    return subprocess.run(
        ["cmd", "/c", str(root / "TradingOS.bat"), *args, "-PythonPath", sys.executable],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=root.parent,
        timeout=120,
        check=False,
    )


def calls_of(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line)["argv"] for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("args", [(), ("Full",), ("full",), ("Infrastructure",), ("-Json",)])
def test_the_modes_that_start_things_start_docker_desktop_first_and_without_arguments(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    root, log = make_bat_tree(tmp_path), tmp_path / "calls.jsonl"
    result = run_bat(root, log, *args)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = calls_of(log)
    assert calls[0] == [
        "docker-script",
        "",
    ]  # first, and called with nothing: the launcher's options are not its business
    assert len(calls) >= 2 and all(
        call[0] == "launcher" for call in calls[1:]
    )  # then the launcher (Full also plans MetaTrader)
    assert [call for call in calls if call[0] == "docker-script"] == [calls[0]]  # exactly once


@pytest.mark.parametrize("args", [("Status",), ("status",), ("Stop", "-DryRun"), ("Doctor",), ("MT5",)])
def test_the_modes_that_only_read_or_stop_never_start_docker_desktop(tmp_path: Path, args: tuple[str, ...]) -> None:
    root, log = make_bat_tree(tmp_path), tmp_path / "calls.jsonl"
    assert run_bat(root, log, *args).returncode == 0
    assert all(call[0] != "docker-script" for call in calls_of(log))
    assert calls_of(log)  # the launcher itself was called


def test_the_start_can_be_told_not_to_touch_docker(tmp_path: Path) -> None:
    root, log = make_bat_tree(tmp_path), tmp_path / "calls.jsonl"
    assert run_bat(root, log, "Full", extra_env={"TRADINGOS_NODOCKERSTART": "1"}).returncode == 0
    assert all(call[0] != "docker-script" for call in calls_of(log))


@pytest.mark.parametrize("code", [1, 2])
def test_a_docker_that_does_not_come_up_stops_nothing_the_launcher_says_it_itself(tmp_path: Path, code: int) -> None:
    root, log = make_bat_tree(tmp_path), tmp_path / "calls.jsonl"
    result = run_bat(root, log, "Infrastructure", docker_exit=code)
    assert result.returncode == 0  # the exit code is the launcher's, not the Docker script's
    assert [call[0] for call in calls_of(log)] == ["docker-script", "launcher"]


def test_a_tree_without_the_docker_script_still_runs_the_launcher(tmp_path: Path) -> None:
    root, log = make_bat_tree(tmp_path, with_docker_script=False), tmp_path / "calls.jsonl"
    assert run_bat(root, log, "Full").returncode == 0
    calls = calls_of(log)
    assert calls and all(
        call[0] == "launcher" for call in calls
    )  # no Docker script, no Docker step, and the launcher ran
