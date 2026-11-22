"""The terminals registry (ADR 0039 § 4, I3): ``var/launcher/terminals.json``, the launcher's memory of each MetaTrader terminal.

It keeps what identifies a terminal and what Exhorte **declares** about it; what the terminal and the EA *report* (server, login, account type) is
read live and never kept. A declaration is checked, and no two terminals may share a magic number, a Trading OS account or an expected login —
the surest way to never address an order to the wrong account. No secret has a field here.

Rules the tests hold it to: a missing file is an empty registry and loading creates nothing; an unreadable one owns nothing and is kept aside when a
new one is written; a valid one is kept aside (``.bak-…``) before it is replaced; the write is atomic; one writer at a time (a lock file); a refusal
leaves the file as it was. **This is the only module of the MetaTrader side that writes**, and it writes only under ``var/launcher``.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from trading_os.launcher.lock import LauncherLock
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.mt5.model import (
    DeclaredTerminal,
    DeploymentRecord,
    OperationKind,
    OperationState,
    PreparedRecord,
    StateRecord,
    TerminalEntry,
    TerminalSource,
    TerminalsSnapshot,
)
from trading_os.launcher.mt5.model import is_overdue as is_overdue  # re-exported: the registry's callers use it
from trading_os.launcher.ports import ProcessTable
from trading_os.shared.time import Clock

TERMINALS_VERSION = 1
MAX_MAGIC = 2**31 - 1
PERIODS = (
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M10",
    "M12",
    "M15",
    "M20",
    "M30",
    "H1",
    "H2",
    "H3",
    "H4",
    "H6",
    "H8",
    "H12",
    "D1",
    "W1",
    "MN1",
)

TERMINAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]{0,39}$")
LABEL = re.compile(r"^[\w .\-]{1,64}$")
SYMBOL = re.compile(r"^[A-Za-z0-9._#@$+\-]{1,32}$")
LOGIN = re.compile(r"^\d{1,15}$")
TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")
ACCOUNT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")


class RegistryRefused(Exception):
    """A change the registry will not make, with every reason (in French: they are shown to a person)."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


# ------------------------------------------------------------------------------------------------ checks


def validate_declared(declared: DeclaredTerminal, others: Sequence[TerminalEntry]) -> list[str]:
    """Every problem of a declaration, against the other terminals of the registry (the one being declared is not among ``others``)."""
    problems: list[str] = []
    if declared.account_id is not None and not ACCOUNT.match(declared.account_id):
        problems.append(
            f"compte Trading OS invalide « {declared.account_id} » : lettres, chiffres, point, tiret, 64 au plus"
        )
    if declared.expected_login is not None and not LOGIN.match(declared.expected_login):
        problems.append(f"login attendu invalide « {declared.expected_login} » : des chiffres seulement (1 à 15)")
    if declared.magic is not None and not 1 <= declared.magic <= MAX_MAGIC:
        problems.append(f"numéro magique invalide {declared.magic} : un entier de 1 à {MAX_MAGIC}")
    if declared.provider is not None and not TOKEN.match(declared.provider):
        problems.append(
            f"fournisseur invalide « {declared.provider} » : majuscules, chiffres et _ (par exemple EXNESS)"
        )
    if declared.product is not None and not TOKEN.match(declared.product):
        problems.append(
            f"produit invalide « {declared.product} » : majuscules, chiffres et _ (par exemple EXNESS_STANDARD)"
        )
    for symbol in declared.allowed_symbols:
        if not SYMBOL.match(symbol):
            problems.append(f"symbole invalide « {symbol} » dans la liste des symboles autorisés")
    if declared.chart is not None:
        if not SYMBOL.match(declared.chart.symbol):
            problems.append(f"symbole invalide « {declared.chart.symbol} » pour le graphique")
        if declared.chart.period not in PERIODS:
            problems.append(f"période invalide « {declared.chart.period} » : une de {', '.join(PERIODS)}")
        if declared.allowed_symbols and declared.chart.symbol not in declared.allowed_symbols:
            problems.append(
                f"le symbole du graphique « {declared.chart.symbol} » n'est pas dans la liste des symboles autorisés"
            )
    for other in others:
        taken = other.declared
        if declared.magic is not None and declared.magic == taken.magic:
            problems.append(
                f"le numéro magique {declared.magic} est déjà utilisé par le terminal {other.terminal_id} ({other.label})"
            )
        if declared.account_id is not None and declared.account_id == taken.account_id:
            problems.append(
                f"le compte Trading OS « {declared.account_id} » est déjà associé au terminal {other.terminal_id} ({other.label})"
            )
        if declared.expected_login is not None and declared.expected_login == taken.expected_login:
            problems.append(
                f"le login attendu {declared.expected_login} est déjà celui du terminal {other.terminal_id} ({other.label})"
            )
    return problems


def terminal_lock(
    config: LauncherConfig, terminal_id: str, processes: ProcessTable, clock: Clock, *, pid: int
) -> LauncherLock:
    """The lock of one terminal: two operations on it are refused, two different terminals do not interfere (ADR 0039 § 4, rule 4)."""
    if not TERMINAL_ID.match(terminal_id):
        raise ValueError(f"identifiant de terminal invalide pour un verrou : {terminal_id!r}")
    return LauncherLock(
        config.locks_dir / f"{terminal_id}.lock",
        processes,
        clock,
        pid=pid,
        description=f"une autre opération sur le terminal {terminal_id} est en cours",
    )


# ------------------------------------------------------------------------------------------------ the registry


class TerminalRegistry:
    def __init__(self, path: Path, clock: Clock, processes: ProcessTable, pid: int) -> None:
        self._path = path
        self._clock = clock
        self._processes = processes
        self._pid = pid

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> TerminalsSnapshot:
        """Never raises, never creates anything."""
        if not self._path.exists():
            return TerminalsSnapshot()
        try:
            document: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            return TerminalsSnapshot(problem=f"registre des terminaux illisible : {error}")
        if not isinstance(document, dict) or document.get("version") != TERMINALS_VERSION:
            return TerminalsSnapshot(problem="registre des terminaux d'une version inconnue ou mal formé")
        try:
            terminals = tuple(TerminalEntry.model_validate(item) for item in document.get("terminals", []))
        except (ValidationError, TypeError) as error:
            return TerminalsSnapshot(problem=f"registre des terminaux mal formé : {error.__class__.__name__}")
        return TerminalsSnapshot(terminals=terminals)

    def register(
        self,
        *,
        terminal_id: str,
        label: str,
        install_path: str,
        data_path: str,
        portable: bool,
        source: TerminalSource,
        declared: DeclaredTerminal | None = None,
    ) -> TerminalEntry:
        problems: list[str] = []
        if not TERMINAL_ID.match(terminal_id):
            problems.append(f"identifiant de terminal invalide « {terminal_id} »")
        if not LABEL.match(label):
            problems.append(
                f"nom de terminal invalide « {label} » : lettres, chiffres, espace, point, tiret, 64 au plus"
            )
        if problems:
            raise RegistryRefused(problems)
        now = self._clock.now()
        entry = TerminalEntry(
            terminal_id=terminal_id,
            label=label,
            install_path=install_path,
            data_path=data_path,
            portable=portable,
            source=source,
            declared=declared or DeclaredTerminal(),
            registered_at=now,
            updated_at=now,
        )

        def add(entries: list[TerminalEntry]) -> list[TerminalEntry]:
            if any(item.terminal_id == terminal_id for item in entries):
                raise RegistryRefused([f"le terminal {terminal_id} est déjà enregistré"])
            checked = validate_declared(entry.declared, entries)
            if checked:
                raise RegistryRefused(checked)
            return [*entries, entry]

        self._mutate(add)
        return entry

    def declare(self, terminal_id: str, declared: DeclaredTerminal) -> TerminalEntry:
        return self._replace(terminal_id, lambda entry, others: self._declared(entry, declared, others))

    def begin_operation(
        self, terminal_id: str, kind: OperationKind, *, deployment_id: str, step: str, timeout_s: float
    ) -> TerminalEntry:
        if kind is OperationKind.IDLE:
            raise RegistryRefused(["IDLE n'est pas une opération à commencer"])
        if timeout_s <= 0:
            raise RegistryRefused(["l'échéance d'une opération doit être positive"])

        def begin(entry: TerminalEntry, _others: Sequence[TerminalEntry]) -> TerminalEntry:
            if entry.operation.kind is not OperationKind.IDLE:
                raise RegistryRefused(
                    [
                        f"le terminal {terminal_id} a déjà une opération en cours : {entry.operation.kind.value} "
                        f"({entry.operation.deployment_id}, étape « {entry.operation.step} »)"
                    ]
                )
            now = self._clock.now()
            operation = OperationState(
                kind=kind,
                deployment_id=deployment_id,
                step=step,
                started_at=now,
                deadline=now + timedelta(seconds=timeout_s),
            )
            return entry.model_copy(update={"operation": operation, "updated_at": now})

        return self._replace(terminal_id, begin)

    def record_deployment(self, terminal_id: str, record: DeploymentRecord) -> TerminalEntry:
        return self._replace(
            terminal_id,
            lambda entry, _others: entry.model_copy(update={"deployment": record, "updated_at": self._clock.now()}),
        )

    def record_prepared(self, terminal_id: str, record: PreparedRecord) -> TerminalEntry:
        return self._replace(
            terminal_id,
            lambda entry, _others: entry.model_copy(update={"prepared": record, "updated_at": self._clock.now()}),
        )

    def record_state(self, terminal_id: str, record: StateRecord) -> TerminalEntry:
        return self._replace(
            terminal_id,
            lambda entry, _others: entry.model_copy(update={"last_state": record, "updated_at": self._clock.now()}),
        )

    def end_operation(self, terminal_id: str) -> TerminalEntry:
        return self._replace(
            terminal_id,
            lambda entry, _others: entry.model_copy(
                update={"operation": OperationState(), "updated_at": self._clock.now()}
            ),
        )

    # ------------------------------------------------------------------------------------------------ internals

    def _declared(
        self, entry: TerminalEntry, declared: DeclaredTerminal, others: Sequence[TerminalEntry]
    ) -> TerminalEntry:
        problems = validate_declared(declared, others)
        if problems:
            raise RegistryRefused(problems)
        return entry.model_copy(update={"declared": declared, "updated_at": self._clock.now()})

    def _replace(
        self, terminal_id: str, change: Callable[[TerminalEntry, Sequence[TerminalEntry]], TerminalEntry]
    ) -> TerminalEntry:
        result: list[TerminalEntry] = []

        def apply(entries: list[TerminalEntry]) -> list[TerminalEntry]:
            current = next((item for item in entries if item.terminal_id == terminal_id), None)
            if current is None:
                raise RegistryRefused([f"terminal inconnu : {terminal_id}"])
            others = [item for item in entries if item.terminal_id != terminal_id]
            changed = change(current, others)
            result.append(changed)
            return [changed if item.terminal_id == terminal_id else item for item in entries]

        self._mutate(apply)
        return result[0]

    def _mutate(self, change: Callable[[list[TerminalEntry]], list[TerminalEntry]]) -> None:
        lock = LauncherLock(
            self._path.with_name(self._path.name + ".lock"),
            self._processes,
            self._clock,
            pid=self._pid,
            description="le registre des terminaux est utilisé par un autre lanceur",
        )
        with lock:
            snapshot = self.load()
            entries = change(list(snapshot.terminals))
            self._write(entries, unreadable=snapshot.problem is not None)

    def _write(self, entries: Sequence[TerminalEntry], *, unreadable: bool) -> None:
        stamp = self._clock.now().strftime("%Y%m%dT%H%M%SZ")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            if unreadable:
                self._path.replace(self._path.with_name(f"{self._path.name}.corrupt-{stamp}"))
            else:
                self._path.with_name(f"{self._path.name}.bak-{stamp}").write_bytes(self._path.read_bytes())
        document = {
            "version": TERMINALS_VERSION,
            "terminals": [item.model_dump(mode="json", by_alias=True) for item in entries],
        }
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self._path)
