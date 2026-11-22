"""Deploying a build of the agent to a registered terminal (ADR 0039 §§ 4 and 7, I4).

What it writes: one file, the ``.ex5`` of our agent (atomically, after keeping the previous one under ``var/launcher/backups/<terminal>/``), and
the launcher's own registry. What it never touches: a junction (it writes *through* it, into the folder it leads to, only if that folder is
ours), ``MQL5\\Files`` (the command store of the EA and the token stay as they are), any other file of the terminal. It refuses — and writes
nothing — a build the compatibility table rejects, a build compiled in a mode other than ``OBSERVE`` or ``CONFIRM`` (ADR 0043), an ``.ex5`` that is not the one its manifest
describes, and a terminal whose data folder no longer belongs to the installation that was registered.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from trading_os.launcher.events import EventLog, EventSeverity, EventType, new_correlation_id
from trading_os.launcher.lock import LauncherBusy
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.mt5.discovery import key_of
from trading_os.launcher.mt5.manifest import AGENT_SOURCE_NAME, EX5_NAME, BuildManifest, sha256_bytes, sha256_file
from trading_os.launcher.mt5.model import DataFolder, DeploymentRecord, EaInstallKind, OperationKind, TerminalEntry
from trading_os.launcher.mt5.ports import Mt5FilesPort
from trading_os.launcher.mt5.terminals import RegistryRefused, TerminalRegistry, terminal_lock
from trading_os.launcher.ports import ProcessTable
from trading_os.shared.agent_compat import assess_agent
from trading_os.shared.time import Clock

DEPLOY_TIMEOUT_S = 120.0
OWN_FOLDER = "TradingOS"  # where a terminal with no agent of ours gets one (ADR 0039 § 4, rule 3)
EXPERT_NAME = "TradingOsAgent"


def terminal_identity_problems(files: Mt5FilesPort, entry: TerminalEntry) -> list[str]:
    """The write path is deduced from the registry and checked again before every write: the data folder must still belong to the registered installation."""
    if entry.portable:
        if not files.is_dir(entry.install_path.rstrip("\\") + "\\MQL5"):
            return [
                f"MT5_TERMINAL_PATH_CHANGED : le dossier MQL5 du terminal portable est introuvable dans {entry.install_path}"
            ]
        return []
    origin = files.read_origin(entry.data_path)
    if origin is None:
        return [f"MT5_TERMINAL_PATH_CHANGED : origin.txt est absent de {entry.data_path} — rien n'est écrit"]
    if key_of(origin) != key_of(entry.install_path):
        return [
            f"MT5_TERMINAL_PATH_CHANGED : origin.txt désigne maintenant {origin}, le terminal enregistré est {entry.install_path} — rien n'est écrit"
        ]
    return []


class DeployRefused(Exception):
    """A deployment that is not made, with every reason (French: shown to a person). Writing nothing is the rule; a failure after the first write says what was undone."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


class DeployAction(StrEnum):
    INSTALL = "INSTALL"  # no .ex5 yet at the target
    REPLACE = "REPLACE"  # a different .ex5 is there: it is kept, then replaced
    UNCHANGED = "UNCHANGED"  # the very same .ex5 is already there


@dataclass(frozen=True)
class DeployPlan:
    terminal_id: str
    target_dir: str
    target_file: str
    expert_path: str  # relative to MQL5\Experts, no extension
    install_kind: str  # JUNCTION / DIRECTORY / NEW
    action: DeployAction
    current_sha256: str | None
    expected_sha256: str
    agent_version: str
    build_name: str


class EaDeployer:
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

    def plan(self, entry: TerminalEntry, folder: DataFolder, manifest: BuildManifest, ex5: Path) -> DeployPlan:
        problems: list[str] = []
        problems.extend(terminal_identity_problems(self._files, entry))
        compat = assess_agent(manifest.agent_version, manifest.capabilities, None)
        if not compat.compatible:
            problems.extend(
                f"build refusé : {reason} ({code})" for code, reason in zip(compat.codes, compat.reasons, strict=True)
            )
        if manifest.compiled_mode not in ("OBSERVE", "CONFIRM") or manifest.mode_ceiling != manifest.compiled_mode:
            problems.append(
                f"le build est compilé en {manifest.compiled_mode} (plafond {manifest.mode_ceiling}) : seuls OBSERVE et CONFIRM, plafond égal au mode, sont déployés (ADR 0043)"
            )
        if not ex5.is_file():
            problems.append(f"le fichier .ex5 du build est introuvable : {ex5}")
        elif sha256_file(ex5) != manifest.ex5_sha256:
            problems.append(
                "l'empreinte du .ex5 ne correspond pas à celle de son manifeste : le build a été modifié, il n'est pas déployé"
            )
        target_dir, kind, expert_path, target_problem = self._target(entry, folder)
        if target_problem:
            problems.append(target_problem)
        if problems:
            raise DeployRefused(problems)
        target_file = target_dir / EX5_NAME
        current = sha256_file(target_file) if target_file.is_file() else None
        if current is None:
            action = DeployAction.INSTALL
        elif current == manifest.ex5_sha256:
            action = DeployAction.UNCHANGED
        else:
            action = DeployAction.REPLACE
        return DeployPlan(
            terminal_id=entry.terminal_id,
            target_dir=str(target_dir),
            target_file=str(target_file),
            expert_path=expert_path,
            install_kind=kind,
            action=action,
            current_sha256=current,
            expected_sha256=manifest.ex5_sha256,
            agent_version=manifest.agent_version,
            build_name=manifest.build_name,
        )

    # ------------------------------------------------------------------------------------------------ apply

    def apply(self, plan: DeployPlan, ex5: Path, manifest: BuildManifest) -> DeploymentRecord:
        """Deploy. The terminal's lock and an operation with a deadline are held for the duration; the operation is ended whatever happens."""
        deployment_id = new_correlation_id()
        try:
            lock = terminal_lock(self._config, plan.terminal_id, self._processes, self._clock, pid=self._pid)
            with lock:
                self._registry.begin_operation(
                    plan.terminal_id,
                    OperationKind.DEPLOYING,
                    deployment_id=deployment_id,
                    step="copie du .ex5",
                    timeout_s=DEPLOY_TIMEOUT_S,
                )
                try:
                    record = self._write(plan, ex5, manifest, deployment_id)
                    self._registry.record_deployment(plan.terminal_id, record)
                finally:
                    self._registry.end_operation(plan.terminal_id)
        except DeployRefused as refused:
            self._refused(plan.terminal_id, deployment_id, refused.problems)
            raise
        except (RegistryRefused, LauncherBusy) as refused:
            problems = refused.problems if isinstance(refused, RegistryRefused) else [str(refused)]
            self._refused(plan.terminal_id, deployment_id, problems)
            raise DeployRefused(problems) from refused
        self._events.emit(
            EventType.MT5_EA_DEPLOYED,
            component="mt5",
            correlation_id=deployment_id,
            instance_id=plan.terminal_id,
            diagnostic=f"agent {record.agent_version} ({plan.action.value}), empreinte {record.ex5_sha256[:12]}, dans {plan.target_dir}",
        )
        return record

    # ------------------------------------------------------------------------------------------------ internals

    def _target(self, entry: TerminalEntry, folder: DataFolder) -> tuple[Path, str, str, str | None]:
        experts = Path(entry.data_path) / "MQL5" / "Experts"
        if folder.eas:
            ea = folder.eas[0]
            expert = f"{ea.name}\\{EXPERT_NAME}"
            if ea.kind is EaInstallKind.JUNCTION:
                if not ea.target:
                    return (
                        experts,
                        "JUNCTION",
                        expert,
                        "la cible de la jonction de l'agent est illisible : rien n'est écrit à travers elle",
                    )
                destination = Path(ea.target)
                if not (destination / AGENT_SOURCE_NAME).is_file():
                    return (
                        destination,
                        "JUNCTION",
                        expert,
                        f"la jonction {ea.name} ne mène pas à un dossier de notre agent ({AGENT_SOURCE_NAME} absent de {destination}) : rien n'est écrit à travers elle",
                    )
                return destination, "JUNCTION", expert, None
            return experts / ea.name, "DIRECTORY", expert, None
        return experts / OWN_FOLDER, "NEW", f"{OWN_FOLDER}\\{EXPERT_NAME}", None

    def _write(self, plan: DeployPlan, ex5: Path, manifest: BuildManifest, deployment_id: str) -> DeploymentRecord:
        target = Path(plan.target_file)
        record = DeploymentRecord(
            deployment_id=deployment_id,
            agent_version=manifest.agent_version,
            ex5_sha256=manifest.ex5_sha256,
            deployed_at=self._clock.now(),
            target_file=plan.target_file,
            expert_path=plan.expert_path,
            build_name=manifest.build_name,
            previous_sha256=plan.current_sha256 if plan.action is DeployAction.REPLACE else None,
        )
        if plan.action is DeployAction.UNCHANGED:
            return record
        previous: bytes | None = target.read_bytes() if target.is_file() else None
        if previous is not None:
            backups = self._config.var_dir / "backups" / plan.terminal_id
            backups.mkdir(parents=True, exist_ok=True)
            (backups / f"{self._clock.now():%Y%m%dT%H%M%SZ}-{EX5_NAME}").write_bytes(previous)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.tmp-{deployment_id}")
        shutil.copyfile(ex5, temporary)
        try:
            os.replace(temporary, target)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise DeployRefused(
                [
                    f"le fichier {target.name} n'a pas pu être remplacé ({error.strerror or error}) : il est sans doute utilisé par le terminal. "
                    "Détachez l'agent du graphique ou fermez le terminal, puis recommencez. L'ancien build est resté en place."
                ]
            ) from error
        if sha256_bytes(target.read_bytes()) != manifest.ex5_sha256:
            if previous is not None:
                shutil.copyfile(self._latest_backup(plan.terminal_id), target)
            else:
                target.unlink(missing_ok=True)
            raise DeployRefused(
                [
                    "la copie ne correspond pas à l'empreinte du manifeste : retour arrière fait ("
                    + ("l'ancien build est remis en place" if previous is not None else "le fichier copié est retiré")
                    + ")"
                ]
            )
        return record

    def _latest_backup(self, terminal_id: str) -> Path:
        return max((self._config.var_dir / "backups" / terminal_id).glob(f"*{EX5_NAME}"), key=lambda item: item.name)

    def _refused(self, terminal_id: str, correlation_id: str, problems: list[str]) -> None:
        self._events.emit(
            EventType.MT5_EA_DEPLOY_REFUSED,
            component="mt5",
            correlation_id=correlation_id,
            severity=EventSeverity.WARNING,
            instance_id=terminal_id,
            diagnostic="; ".join(problems),
        )
