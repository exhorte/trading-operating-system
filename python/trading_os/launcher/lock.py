"""One launcher at a time (ADR 0038, § 4). Two concurrent runs must not both start the application, nor a stop run under a start.

The lock is a file holding its owner's pid and creation time. A live owner refuses the second run; a stale lock — the owner is gone, its pid
was recycled, or the file is unreadable — is replaced, because a lock that nobody can prove is held protects nobody.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import TracebackType

from trading_os.launcher.model import ProcessInfo
from trading_os.launcher.ports import ProcessTable
from trading_os.shared.time import Clock, iso, parse_iso

SAME_PROCESS_TOLERANCE = timedelta(seconds=1)


class LauncherBusy(Exception):
    """Another launcher is running."""


class LauncherLock:
    def __init__(
        self,
        path: Path,
        processes: ProcessTable,
        clock: Clock,
        *,
        pid: int,
        description: str = "un autre lanceur tourne",
    ) -> None:
        self._description = description
        self._path = path
        self._processes = processes
        self._clock = clock
        self._pid = pid
        self._held = False

    def __enter__(self) -> LauncherLock:
        self.acquire()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.release()

    def acquire(self) -> None:
        table = {process.pid: process for process in self._processes.processes()}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                holder = self._holder(table)
                if holder is not None:
                    raise LauncherBusy(f"{self._description} (pid {holder}) : attendre qu'il ait fini") from None
                self._path.unlink(missing_ok=True)  # stale: nobody can prove it is held
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                own = table.get(self._pid)
                created = own.created_at if own is not None and own.created_at is not None else self._clock.now()
                json.dump({"pid": self._pid, "createdAt": iso(created)}, handle)
            self._held = True
            return
        raise LauncherBusy("le verrou du lanceur est disputé : réessayer")

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        with contextlib.suppress(OSError, ValueError):
            document = json.loads(self._path.read_text(encoding="utf-8"))
            if document.get("pid") == self._pid:  # never remove somebody else's lock
                self._path.unlink(missing_ok=True)

    def _holder(self, table: dict[int, ProcessInfo]) -> int | None:
        """The pid of the live owner of the existing lock, or ``None`` when the lock is stale."""
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            pid = int(document["pid"])
            created = parse_iso(str(document["createdAt"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return pid if _is_alive(pid, created, table) else None


def _is_alive(pid: int, created: datetime, table: dict[int, ProcessInfo]) -> bool:
    """The recorded process is still there: same pid *and* same creation time (a recycled pid is somebody else)."""
    process = table.get(pid)
    if process is None or process.created_at is None:
        return False
    return abs(process.created_at - created) <= SAME_PROCESS_TOLERANCE


class LockState(StrEnum):
    FREE = "FREE"  # no lock file
    HELD = "HELD"  # a live launcher holds it
    STALE = "STALE"  # a file nobody can prove is held: its owner is gone, its pid was recycled, or it cannot be read


@dataclass(frozen=True)
class LockInspection:
    state: LockState
    pid: int | None = None


def inspect_lock(path: Path, processes: ProcessTable) -> LockInspection:
    """Look at the lock and say what it is. Takes nothing, replaces nothing, removes nothing; the process table is read only when a file exists."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return LockInspection(LockState.FREE)
    except (OSError, ValueError):
        return LockInspection(LockState.STALE)
    try:
        pid = int(document["pid"])
        created = parse_iso(str(document["createdAt"]))
    except (KeyError, TypeError, ValueError):
        return LockInspection(LockState.STALE)
    table = {process.pid: process for process in processes.processes()}
    return LockInspection(LockState.HELD if _is_alive(pid, created, table) else LockState.STALE, pid)
