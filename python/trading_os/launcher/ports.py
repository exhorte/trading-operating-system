"""Everything the launcher does to the outside world goes through these ports (ADR 0038, § 2) — so a test can stand in for the machine.

I1 only **looks**: no port has a method that starts, stops, writes or reads a file's content. ``EnvironmentPort`` in particular can say
that a path exists or where a tool is, and nothing else: the launcher cannot read ``.env`` through it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trading_os.launcher.model import ContainerInfo, CoreHealth, Listener, ProcessInfo


class ProbeError(Exception):
    """Something that had to be read could not be read. The launcher fails closed on it: an unreadable process table is not an empty one."""


class SpawnError(Exception):
    """A process could not be started."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(
        self, args: Sequence[str], *, timeout: float, cwd: Path | None = None, stdin: str | None = None
    ) -> CommandResult: ...


class Sleeper(Protocol):
    def sleep(self, seconds: float) -> None: ...


class ProcessSpawner(Protocol):
    """Starts a detached process whose output goes to ``log_path``; returns its pid. The only thing that starts a process of the system."""

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int: ...


class ProcessController(Protocol):
    """Ends a process **by pid, for a pid the registry owns** — the caller proves ownership, this port does not. The only way out."""

    def request_stop(self, pid: int) -> bool: ...

    def terminate_tree(self, pid: int) -> bool: ...

    def request_window_close(self, pid: int) -> bool:
        """Ask the windows of a process to close, the way a person does with the close button — never a kill. For a process the registry does not own,
        only after the typed confirmation and the gates of ``mt5/control.py``."""
        ...


class DockerActions(Protocol):
    def start_container(self, name: str) -> bool: ...

    def create_database(self, repo_root: Path) -> bool: ...

    def stop_container(self, name: str) -> bool: ...

    def dump_database(self, container: str, destination: Path) -> bool: ...


class ProcessTable(Protocol):
    def processes(self) -> list[ProcessInfo]: ...

    def listeners(self, ports: Sequence[int]) -> list[Listener]: ...


class DockerPort(Protocol):
    def available(self) -> bool: ...

    def container(self, name: str) -> ContainerInfo | None: ...

    def port_holders(self, port: int) -> list[str]: ...


class HealthProbe(Protocol):
    def core_health(self, url: str) -> CoreHealth | None: ...

    def http_status(self, url: str) -> int | None: ...


class EnvironmentPort(Protocol):
    def path_exists(self, path: Path) -> bool: ...

    def which(self, name: str) -> str | None: ...
