"""Fakes for the controlled start of a terminal (ADR 0039 §§ 3 and 5, I6). The terminal is a process in a fake table, the probe says what it is told to say, the
spawner adds a process, the controller removes one when it is *asked* — a fake MetaTrader that either obeys or does not. A fake clock and a sleeper that moves it
keep a ninety-second wait instantaneous."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from tests.unit.launcher.mt5.support_deploy import TERMINAL_ID, World, sha
from tests.unit.launcher.support import FakeHealth, core_health, proc
from trading_os.launcher.events import EventLog
from trading_os.launcher.model import Mt5WorkersFacts
from trading_os.launcher.mt5.control import Mt5Controller
from trading_os.launcher.mt5.model import CenterFacts, TerminalEntry, TerminalSnapshot, TerminalVerdict
from trading_os.launcher.ports import ProbeError, SpawnError
from trading_os.shared.time import ManualClock

EXE_NAME = "terminal64.exe"


class FakeProbe:
    def __init__(self, snapshot: TerminalSnapshot | None = None, error: str | None = None) -> None:
        self.snapshot = snapshot or TerminalSnapshot(login="486046157", positions=0, orders=0)
        self.error = error
        self.calls: list[str] = []

    def read(self, exe_path: str) -> TerminalSnapshot:
        self.calls.append(exe_path)
        if self.error:
            raise ProbeError(self.error)
        return self.snapshot


class FakeCenter:
    """The core's side: says nothing until a hello is scheduled."""

    def __init__(self) -> None:
        self.facts = CenterFacts(reachable=True, hello_received=False)
        self.asked = 0
        self._after: tuple[int, CenterFacts] | None = None

    def hello_after(self, asks: int, facts: CenterFacts) -> None:
        self._after = (asks, facts)

    def terminal_facts(self, entry: TerminalEntry) -> CenterFacts:
        self.asked += 1
        if self._after and self.asked >= self._after[0]:
            return self._after[1]
        return self.facts


class Machine:
    """A world in which the terminal can run, be asked to close, and be started."""

    def __init__(self, tmp: Path, *, running: bool, obeys: bool = True, starts: bool = True) -> None:
        self.world = World(tmp, ea="directory")
        self.world.registry.declare(TERMINAL_ID, _declared())
        manifest, ex5 = self.world.built(ex5=b"EX5 build of 1.13")
        plan = self.world.deployer.plan(self.world.entry(), self.world.folder(), manifest, ex5)
        self.world.deployer.apply(plan, ex5, manifest)
        from trading_os.launcher.mt5.prepare import Preparer

        preparer = Preparer(
            self.world.files,
            self.world.config,
            self.world.clock,
            self.world.registry,
            self.world.events,
            self.world.processes,
            pid=4242,
        )
        preparer.apply(preparer.plan(self.world.entry()))
        self.exe = str(self.world.install / EXE_NAME)
        self.running_pid: int | None = 1872 if running else None
        self.obeys = obeys
        self.starts = starts
        self.clock: ManualClock = self.world.clock
        self.table = self.world.processes
        if running:
            self.table._processes.append(proc(1872, name=EXE_NAME, executable=self.exe))
        self.closed_asked: list[int] = []
        self.spawned: list[list[str]] = []
        self.probe = FakeProbe()
        self.center = FakeCenter()
        self.health = FakeHealth(None)  # the core is down unless a test says otherwise
        self.sleeps: list[float] = []
        self.on_sleep: Callable[[], None] | None = None

    # --- the ports
    def request_window_close(self, pid: int) -> bool:
        self.closed_asked.append(pid)
        if self.obeys:
            self.table._processes[:] = [p for p in self.table._processes if p.pid != pid]
        return True

    def request_stop(self, pid: int) -> bool:  # never called by the controller of a terminal
        raise AssertionError("a terminal is never stopped by the launcher's own stop")

    def terminate_tree(self, pid: int) -> bool:  # never called either: MetaTrader is never killed
        raise AssertionError("MetaTrader is never killed")

    def spawn(self, args, *, cwd: Path, log_path: Path) -> int:  # type: ignore[no-untyped-def]
        self.spawned.append(list(args))
        if not self.starts:
            raise SpawnError("introuvable")
        self.running_pid = 4321
        self.table._processes.append(proc(4321, name=EXE_NAME, executable=self.exe))
        return 4321

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.advance(seconds=seconds)
        if self.on_sleep:
            self.on_sleep()

    def with_workers(self, alive: int) -> None:
        self.health = FakeHealth(core_health(mt5_workers=Mt5WorkersFacts(spawned=alive, ended=0, alive=alive)))

    def controller(self) -> Mt5Controller:
        return Mt5Controller(
            files=self.world.files,
            processes=self.table,
            spawner=self,
            controller=self,
            probe=self.probe,
            center=self.center,
            health=self.health,
            registry=self.world.registry,
            events=EventLog(self.world.config.events_dir, self.clock),
            clock=self.clock,
            sleeper=self,
            config=self.world.config,
            pid=4242,
        )

    def entry(self) -> TerminalEntry:
        return self.world.entry()


def _declared():  # type: ignore[no-untyped-def]
    from tests.unit.launcher.mt5.support import declared

    return declared()


def ready(version: str = "1.13") -> CenterFacts:
    return CenterFacts(
        reachable=True, hello_received=True, verdict=TerminalVerdict(verdict="VALIDATING", agent_version=version)
    )


__all__ = ["EXE_NAME", "UTC", "FakeCenter", "FakeProbe", "Machine", "datetime", "ready", "sha"]
