"""Preparing a terminal for the agent (ADR 0039 §§ 4 and 5, I5): the preset in ``MQL5\\Presets`` and the start-up file the launcher keeps for itself.

It writes two files — ``MQL5\\Presets\\TradingOS-<terminal>.set`` (the only thing it adds to a terminal) and ``var/launcher/mt5/<terminal>/startup.ini`` —
after keeping any previous preset under ``var/launcher/backups/<terminal>/``. It refuses, and writes nothing: a declaration that is incomplete, an
agent that was not deployed (or whose ``.ex5`` is no longer the one that was), a terminal whose data folder no longer belongs to the registered
installation. It is given no password and no token and starts nothing; ``/config`` is used later, by the controlled start, with the file made here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from trading_os.launcher.events import EventLog, EventSeverity, EventType, new_correlation_id
from trading_os.launcher.lock import LauncherBusy
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.mt5.deploy import terminal_identity_problems
from trading_os.launcher.mt5.manifest import AGENT_SOURCE_NAME, sha256_bytes, sha256_file
from trading_os.launcher.mt5.model import ChartSpec, OperationKind, PreparedRecord, TerminalEntry
from trading_os.launcher.mt5.ports import Mt5FilesPort
from trading_os.launcher.mt5.preset import PresetRefused, build_preset, parse_inputs, render_set
from trading_os.launcher.mt5.startup_ini import render_startup_ini
from trading_os.launcher.mt5.terminals import RegistryRefused, TerminalRegistry, terminal_lock
from trading_os.launcher.ports import ProcessTable
from trading_os.shared.time import Clock

PREPARE_TIMEOUT_S = 60.0


class PrepareRefused(Exception):
    """A preparation that is not made, with every reason (French: shown to a person)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


class PrepareAction(StrEnum):
    INSTALL = "INSTALL"
    REPLACE = "REPLACE"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True)
class PreparePlan:
    terminal_id: str
    preset_path: str
    startup_path: str
    expert_path: str
    chart: ChartSpec
    preset_action: PrepareAction
    startup_action: PrepareAction
    preset_bytes: bytes = field(repr=False)
    startup_bytes: bytes = field(repr=False)
    preset_lines: tuple[
        str, ...
    ] = ()  # what the preset says, for a person to read (never anything secret: there is nothing secret in it)


class Preparer:
    def __init__(
        self,
        files: Mt5FilesPort,
        config: LauncherConfig,
        clock: Clock,
        registry: TerminalRegistry,
        events: EventLog,
        processes: ProcessTable,
        *,
        pid: int,
    ) -> None:
        self._files = files
        self._config = config
        self._clock = clock
        self._registry = registry
        self._events = events
        self._processes = processes
        self._pid = pid

    # ------------------------------------------------------------------------------------------------ plan (reads, writes nothing)

    def plan(self, entry: TerminalEntry) -> PreparePlan:
        problems = terminal_identity_problems(self._files, entry)
        if entry.deployment is None:
            problems.append("aucun agent n'est déployé sur ce terminal : « launcher mt5 deploy » d'abord")
        else:
            deployed = Path(entry.deployment.target_file)
            if not deployed.is_file():
                problems.append(f"l'agent déployé a disparu ({deployed}) : redéployez-le")
            elif sha256_file(deployed) != entry.deployment.ex5_sha256:
                problems.append(
                    "l'agent déployé a changé depuis son déploiement (empreinte différente) : redéployez-le"
                )
        source = self._config.repo_root / "tools" / "mt5-execution-agent" / AGENT_SOURCE_NAME
        inputs = parse_inputs(source.read_text(encoding="utf-8", errors="replace")) if source.is_file() else []
        if not inputs:
            problems.append(f"les entrées de l'agent sont illisibles ({source})")
        preset_bytes = b""
        preset_lines: tuple[str, ...] = ()
        try:
            preset = build_preset(entry.declared, inputs, core_port=self._config.ea_link_port) if inputs else None
        except PresetRefused as refused:
            problems.extend(refused.problems)
            preset = None
        if preset is not None:
            preset_bytes = render_set(preset)
            preset_lines = tuple(f"{name}={value}" for name, value in preset.values)
        if problems or entry.deployment is None or preset is None or entry.declared.chart is None:
            raise PrepareRefused(problems or ["préparation impossible"])
        preset_name = f"TradingOS-{entry.terminal_id}.set"
        startup_bytes = render_startup_ini(entry.deployment.expert_path, preset_name, entry.declared.chart).encode(
            "utf-8"
        )
        preset_path = Path(entry.data_path) / "MQL5" / "Presets" / preset_name
        startup_path = self._startup_path(entry.terminal_id)
        return PreparePlan(
            terminal_id=entry.terminal_id,
            preset_path=str(preset_path),
            startup_path=str(startup_path),
            expert_path=entry.deployment.expert_path,
            chart=entry.declared.chart,
            preset_action=_action(preset_path, preset_bytes),
            startup_action=_action(startup_path, startup_bytes),
            preset_bytes=preset_bytes,
            startup_bytes=startup_bytes,
            preset_lines=preset_lines,
        )

    # ------------------------------------------------------------------------------------------------ apply

    def apply(self, plan: PreparePlan) -> PreparedRecord:
        correlation = new_correlation_id()
        try:
            with terminal_lock(self._config, plan.terminal_id, self._processes, self._clock, pid=self._pid):
                self._registry.begin_operation(
                    plan.terminal_id,
                    OperationKind.DEPLOYING,
                    deployment_id=correlation,
                    step="preset et fichier de démarrage",
                    timeout_s=PREPARE_TIMEOUT_S,
                )
                try:
                    record = self._write(plan)
                    self._registry.record_prepared(plan.terminal_id, record)
                finally:
                    self._registry.end_operation(plan.terminal_id)
        except PrepareRefused as refused:
            self._refused(plan.terminal_id, correlation, refused.problems)
            raise
        except (RegistryRefused, LauncherBusy) as refused:
            problems = refused.problems if isinstance(refused, RegistryRefused) else [str(refused)]
            self._refused(plan.terminal_id, correlation, problems)
            raise PrepareRefused(problems) from refused
        self._events.emit(
            EventType.MT5_PRESET_WRITTEN,
            component="mt5",
            correlation_id=correlation,
            instance_id=plan.terminal_id,
            diagnostic=f"preset {plan.preset_action.value} et fichier de démarrage {plan.startup_action.value} ; graphique {plan.chart.symbol} {plan.chart.period}",
        )
        return record

    # ------------------------------------------------------------------------------------------------ internals

    def _startup_path(self, terminal_id: str) -> Path:
        return self._config.var_dir / "mt5" / terminal_id / "startup.ini"

    def _write(self, plan: PreparePlan) -> PreparedRecord:
        preset = Path(plan.preset_path)
        startup = Path(plan.startup_path)
        if plan.preset_action is PrepareAction.REPLACE:
            backups = self._config.var_dir / "backups" / plan.terminal_id
            backups.mkdir(parents=True, exist_ok=True)
            (backups / f"{self._clock.now():%Y%m%dT%H%M%SZ}-{preset.name}").write_bytes(preset.read_bytes())
        if plan.preset_action is not PrepareAction.UNCHANGED:
            self._atomic(preset, plan.preset_bytes)
        if plan.startup_action is not PrepareAction.UNCHANGED:
            self._atomic(startup, plan.startup_bytes)
        return PreparedRecord(
            prepared_at=self._clock.now(),
            preset_path=plan.preset_path,
            preset_sha256=sha256_bytes(plan.preset_bytes),
            startup_path=plan.startup_path,
            startup_sha256=sha256_bytes(plan.startup_bytes),
        )

    @staticmethod
    def _atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        try:
            os.replace(temporary, path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise PrepareRefused(
                [f"{path.name} n'a pas pu être écrit ({error.strerror or error}) : l'ancien fichier est resté en place"]
            ) from error

    def _refused(self, terminal_id: str, correlation_id: str, problems: list[str]) -> None:
        self._events.emit(
            EventType.MT5_PREPARE_REFUSED,
            component="mt5",
            correlation_id=correlation_id,
            severity=EventSeverity.WARNING,
            instance_id=terminal_id,
            diagnostic="; ".join(problems),
        )


def _action(path: Path, content: bytes) -> PrepareAction:
    if not path.is_file():
        return PrepareAction.INSTALL
    return PrepareAction.UNCHANGED if path.read_bytes() == content else PrepareAction.REPLACE
