"""The registry (ADR 0038, § 3): the launcher's only memory of what it started, kept in a file because it runs before the database.

It records the **processes** it started (pid and creation time) and the **containers** it started. Rules the tests hold it to: a missing file is
an empty registry; an **unreadable** one owns nothing (and is kept aside as evidence when the launcher writes a new one); a command line is
masked before it is written; the write is atomic; and a process entry counts only while a live process has the recorded pid **and** the
recorded creation time (Windows reuses pids). One writer at a time: ``lock.py`` makes it a rule.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from trading_os.domain.primitives import DomainModel
from trading_os.launcher.model import Component, OwnedContainer, OwnedProcess, ProcessInfo
from trading_os.shared.logging.redaction import redact
from trading_os.shared.time import Clock

REGISTRY_VERSION = 1
SAME_PROCESS_TOLERANCE = timedelta(seconds=1)


class RegistrySnapshot(DomainModel):
    owned: tuple[OwnedProcess, ...] = ()
    containers: tuple[OwnedContainer, ...] = ()
    problem: str | None = None


def verify_owned(entries: Sequence[OwnedProcess], table: Sequence[ProcessInfo]) -> tuple[OwnedProcess, ...]:
    """The entries whose process is alive *and is the same process*. When the identity cannot be proved, it is not ours."""
    live = {process.pid: process for process in table}
    verified: list[OwnedProcess] = []
    for entry in entries:
        process = live.get(entry.pid)
        if process is None or process.created_at is None:
            continue
        if abs(process.created_at - entry.created_at) <= SAME_PROCESS_TOLERANCE:
            verified.append(entry)
    return tuple(verified)


class ProcessRegistry:
    def __init__(self, path: Path, clock: Clock) -> None:
        self._path = path
        self._clock = clock

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> RegistrySnapshot:
        """Never raises, never creates anything."""
        if not self._path.exists():
            return RegistrySnapshot()
        try:
            document: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return RegistrySnapshot(problem=f"registre illisible : {error}")
        if not isinstance(document, dict) or document.get("version") != REGISTRY_VERSION:
            return RegistrySnapshot(problem="registre d'une version inconnue ou mal formé")
        try:
            owned = tuple(OwnedProcess.model_validate(item) for item in document.get("owned", []))
            containers = tuple(OwnedContainer.model_validate(item) for item in document.get("containers", []))
        except (ValidationError, TypeError) as error:
            return RegistrySnapshot(problem=f"registre mal formé : {error.__class__.__name__}")
        return RegistrySnapshot(owned=owned, containers=containers)

    def record(self, owned: OwnedProcess) -> None:
        safe = owned.model_copy(update={"command_line": redact(owned.command_line)})
        processes, containers = self._current()
        self._write([item for item in processes if item.component is not safe.component] + [safe], containers)

    def forget(self, component: Component) -> None:
        if not self._path.exists():
            return
        processes, containers = self._current()
        self._write([item for item in processes if item.component is not component], containers)

    def record_container(self, container: OwnedContainer) -> None:
        processes, containers = self._current()
        self._write(processes, [item for item in containers if item.name != container.name] + [container])

    def forget_container(self, name: str) -> None:
        if not self._path.exists():
            return
        processes, containers = self._current()
        self._write(processes, [item for item in containers if item.name != name])

    # ------------------------------------------------------------------------------------------------ internals

    def _current(self) -> tuple[list[OwnedProcess], list[OwnedContainer]]:
        snapshot = self.load()
        if snapshot.problem is not None:
            self._keep_aside()
            return [], []
        return list(snapshot.owned), list(snapshot.containers)

    def _keep_aside(self) -> None:
        stamp = self._clock.now().strftime("%Y%m%dT%H%M%SZ")
        self._path.replace(self._path.with_name(f"{self._path.name}.corrupt-{stamp}"))

    def _write(self, processes: Sequence[OwnedProcess], containers: Sequence[OwnedContainer]) -> None:
        document = {
            "version": REGISTRY_VERSION,
            "owned": [item.model_dump(mode="json", by_alias=True) for item in processes],
            "containers": [item.model_dump(mode="json", by_alias=True) for item in containers],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self._path)
