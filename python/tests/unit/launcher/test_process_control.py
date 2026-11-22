"""The real thing, on harmless children (ADR 0038, I2): the spawner starts a detached process with its output in a log, the controller asks it to
stop politely (a console Ctrl+C) and ends a whole tree. **Every process here is one this test started itself** — nothing of the system is touched.

Windows only: a console Ctrl+C has no equivalent elsewhere."""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from trading_os.launcher.actions import SubprocessSpawner
from trading_os.launcher.adapters import SubprocessRunner
from trading_os.launcher.ports import SpawnError
from trading_os.launcher.process_control import WindowsProcessController

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="console Ctrl+C is a Windows mechanism here")

POLITE_SLEEPER = """
import os, pathlib, signal, sys, time
base = pathlib.Path(sys.argv[1])
def stop(*_):
    base.with_suffix(".graceful").write_text("yes")
    sys.exit(0)
signal.signal(signal.SIGBREAK, stop)  # what uvicorn does too: Ctrl+Break is an orderly shutdown
base.with_suffix(".ready").write_text(str(os.getpid()))
while True:
    time.sleep(0.1)
"""

PARENT_WITH_CHILD = """
import pathlib, subprocess, sys, time
base = pathlib.Path(sys.argv[1])
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
base.with_suffix(".child").write_text(str(child.pid))
base.with_suffix(".ready").write_text("up")
time.sleep(120)
"""


def alive(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True, check=False
    ).stdout
    return f'"{pid}"' in out


def wait_for(condition: Callable[[], bool], seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


@pytest.fixture
def controller() -> WindowsProcessController:
    return WindowsProcessController(SubprocessRunner())


@pytest.fixture
def cleanup(controller: WindowsProcessController) -> Iterator[list[int]]:
    """Whatever the test leaves alive — and only that, since the pids are the test's own — is ended at the end."""
    pids: list[int] = []
    yield pids
    for pid in pids:
        if alive(pid):
            controller.terminate_tree(pid)


class TestTheSpawner:
    def test_the_output_goes_to_the_log_and_the_process_is_independent_of_the_caller(
        self, tmp_path: Path, cleanup: list[int]
    ) -> None:
        log = tmp_path / "logs" / "hello.log"
        pid = SubprocessSpawner().spawn(
            [sys.executable, "-c", "print('hello from the child')"], cwd=tmp_path, log_path=log
        )
        cleanup.append(pid)
        assert wait_for(
            lambda: log.exists() and "hello from the child" in log.read_text(encoding="utf-8", errors="replace")
        )

    def test_it_runs_in_the_directory_it_is_given(self, tmp_path: Path, cleanup: list[int]) -> None:
        log = tmp_path / "where.log"
        pid = SubprocessSpawner().spawn(
            [sys.executable, "-c", "import os; print(os.getcwd())"], cwd=tmp_path, log_path=log
        )
        cleanup.append(pid)
        assert wait_for(lambda: log.exists() and str(tmp_path) in log.read_text(encoding="utf-8", errors="replace"))

    def test_a_program_that_does_not_exist_is_a_spawn_error(self, tmp_path: Path) -> None:
        with pytest.raises(SpawnError):
            SubprocessSpawner().spawn(["definitely-not-a-real-program-name"], cwd=tmp_path, log_path=tmp_path / "x.log")


class TestTheController:
    def test_a_polite_request_reaches_a_process_with_its_own_console_and_it_exits_by_itself(
        self, tmp_path: Path, controller: WindowsProcessController, cleanup: list[int]
    ) -> None:
        base = tmp_path / "polite"
        pid = SubprocessSpawner().spawn(
            [sys.executable, "-c", POLITE_SLEEPER, str(base)], cwd=tmp_path, log_path=tmp_path / "p.log"
        )
        cleanup.append(pid)
        assert wait_for(lambda: base.with_suffix(".ready").exists()), "the child never started"
        assert controller.request_stop(pid) is True
        assert wait_for(lambda: base.with_suffix(".graceful").exists()), "the child did not receive Ctrl+Break"
        assert wait_for(lambda: not alive(pid))

    def test_the_request_reaches_only_the_process_it_names(
        self, tmp_path: Path, controller: WindowsProcessController, cleanup: list[int]
    ) -> None:
        first, second = tmp_path / "first", tmp_path / "second"
        spawner = SubprocessSpawner()
        a = spawner.spawn([sys.executable, "-c", POLITE_SLEEPER, str(first)], cwd=tmp_path, log_path=tmp_path / "a.log")
        b = spawner.spawn(
            [sys.executable, "-c", POLITE_SLEEPER, str(second)], cwd=tmp_path, log_path=tmp_path / "b.log"
        )
        cleanup.extend([a, b])
        assert wait_for(lambda: first.with_suffix(".ready").exists() and second.with_suffix(".ready").exists())
        assert controller.request_stop(a) is True
        assert wait_for(lambda: first.with_suffix(".graceful").exists())
        time.sleep(1.0)
        assert alive(b), "a neighbour was stopped with it"
        assert not second.with_suffix(".graceful").exists()

    def test_a_process_that_is_not_the_leader_of_its_own_group_cannot_be_asked_politely_and_survives_the_attempt(
        self, controller: WindowsProcessController, cleanup: list[int]
    ) -> None:
        """The case of an adopted process, started by hand: Windows refuses, the caller is told, nothing is signalled."""
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        cleanup.append(process.pid)
        time.sleep(0.5)
        assert controller.request_stop(process.pid) is False
        assert alive(process.pid)

    def test_a_whole_tree_is_ended(
        self, tmp_path: Path, controller: WindowsProcessController, cleanup: list[int]
    ) -> None:
        base = tmp_path / "tree"
        parent = SubprocessSpawner().spawn(
            [sys.executable, "-c", PARENT_WITH_CHILD, str(base)], cwd=tmp_path, log_path=tmp_path / "t.log"
        )
        cleanup.append(parent)
        assert wait_for(lambda: base.with_suffix(".ready").exists())
        child = int(base.with_suffix(".child").read_text())
        cleanup.append(child)
        assert alive(parent) and alive(child)
        assert controller.terminate_tree(parent) is True
        assert wait_for(lambda: not alive(parent) and not alive(child)), "the child survived its parent"

    def test_a_process_that_is_already_gone_counts_as_stopped(self, controller: WindowsProcessController) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait()
        assert controller.terminate_tree(process.pid) is True

    def test_a_polite_request_to_a_process_that_does_not_exist_is_false(
        self, controller: WindowsProcessController
    ) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait()
        assert controller.request_stop(process.pid) is False
