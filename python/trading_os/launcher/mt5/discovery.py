"""Finding the MetaTrader 5 terminals (ADR 0038 § 6, I3): installations, data folders, running instances. **Read-only**, and nothing is assumed.

A location is believed only once ``terminal64.exe`` is found in it. A data folder belongs to an installation only because the terminal itself wrote
that installation in the folder's ``origin.txt``. Several terminals are listed and **none is ever chosen**. A running terminal's command line is read
for two facts (``/portable``, ``/config:``) and then dropped: it can carry a login and a password.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import PureWindowsPath

from trading_os.launcher.mt5.model import (
    DataFolder,
    DiscoveryResult,
    DiscoverySource,
    EaInstall,
    EaInstallKind,
    Installation,
    Mt5Config,
    RejectedCandidate,
    RunningTerminal,
)
from trading_os.launcher.mt5.ports import DirEntry, InstalledProgramsPort, Mt5FilesPort
from trading_os.launcher.ports import ProcessTable
from trading_os.shared.time import Clock

EXE_NAME = "terminal64.exe"
HEX32 = re.compile(r"^[0-9A-Fa-f]{32}$")
OUR_EA_NAMES = frozenset({"tradingosagent", "tradingos"})
MAX_LISTED = 50
SOURCE_ORDER = (
    DiscoverySource.REGISTRY,
    DiscoverySource.KNOWN_DIRECTORY,
    DiscoverySource.RUNNING_PROCESS,
    DiscoverySource.REGISTERED,
)
SHOW_PRIORITY = (  # which spelling of a path to show when several sources name it: the one the machine itself gave
    DiscoverySource.RUNNING_PROCESS,
    DiscoverySource.KNOWN_DIRECTORY,
    DiscoverySource.REGISTERED,
    DiscoverySource.REGISTRY,
)


def normalize(path: str) -> str:
    return str(PureWindowsPath(path))


def key_of(path: str) -> str:
    return normalize(path).lower()


def portable_id(path: str) -> str:
    """The identifier of a terminal that has no data-folder name of its own: stable, and blind to letter case."""
    return "portable-" + hashlib.sha256(key_of(path).encode("utf-8")).hexdigest()[:16]


def data_folder_id(path: str) -> str:
    """The name MetaTrader gave the data folder (32 hexadecimal characters), upper-cased; anything else gets a stable derived identifier."""
    name = PureWindowsPath(path).name
    return (
        name.upper() if HEX32.match(name) else "manual-" + hashlib.sha256(key_of(path).encode("utf-8")).hexdigest()[:16]
    )


def _executable_of(process_executable: str | None, command_line: str) -> str | None:
    if process_executable:
        return process_executable
    text = command_line.strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end] if end > 0 else None
    cut = text.lower().find(".exe")
    return text[: cut + 4] if cut >= 0 else None


class _Candidate:
    def __init__(self) -> None:
        self.shown: dict[DiscoverySource, str] = {}

    def add(self, source: DiscoverySource, path: str) -> None:
        self.shown.setdefault(source, normalize(path))

    @property
    def sources(self) -> tuple[DiscoverySource, ...]:
        return tuple(source for source in SOURCE_ORDER if source in self.shown)

    @property
    def display(self) -> str:
        for source in SHOW_PRIORITY:
            if source in self.shown:
                return self.shown[source]
        raise ValueError("a candidate without a source")


class Mt5Discovery:
    def __init__(
        self,
        config: Mt5Config,
        *,
        files: Mt5FilesPort,
        programs: InstalledProgramsPort,
        processes: ProcessTable,
        clock: Clock,
    ) -> None:
        self._config = config
        self._files = files
        self._programs = programs
        self._processes = processes
        self._clock = clock

    def discover(self, extra_install_paths: Sequence[str] = ()) -> DiscoveryResult:
        candidates: dict[str, _Candidate] = {}
        running: dict[str, list[RunningTerminal]] = {}

        def add(source: DiscoverySource, path: str) -> None:
            candidates.setdefault(key_of(path), _Candidate()).add(source, path)

        for program in self._programs.programs():
            if "metatrader" in program.display_name.lower():
                for location in program.locations:
                    add(DiscoverySource.REGISTRY, location)
        for root in self._config.program_roots:
            for entry in self._files.list_directory(root):
                if entry.is_dir and "metatrader" in entry.name.lower():
                    add(DiscoverySource.KNOWN_DIRECTORY, str(PureWindowsPath(root) / entry.name))
        for process in self._processes.processes():
            if process.name.lower() != EXE_NAME:
                continue
            executable = _executable_of(process.executable, process.command_line)
            if not executable:
                continue
            folder = str(PureWindowsPath(executable).parent)
            add(DiscoverySource.RUNNING_PROCESS, folder)
            line = process.command_line.lower()
            running.setdefault(key_of(folder), []).append(
                RunningTerminal(
                    pid=process.pid,
                    created_at=process.created_at,
                    portable="/portable" in line,
                    config_file_given="/config:" in line,
                )
            )
        for path in extra_install_paths:
            add(DiscoverySource.REGISTERED, path)

        accepted: list[tuple[str, _Candidate]] = []
        rejected: list[RejectedCandidate] = []
        for candidate_key in sorted(candidates):
            candidate = candidates[candidate_key]
            if self._files.is_file(str(PureWindowsPath(candidate.display) / EXE_NAME)):
                accepted.append((candidate_key, candidate))
            else:
                rejected.append(
                    RejectedCandidate(
                        path=candidate.display,
                        source=candidate.sources[0],
                        reason=f"{EXE_NAME} est introuvable dans ce dossier",
                    )
                )

        owned_keys = {candidate_key for candidate_key, _ in accepted}
        origins = self._data_folders_by_origin()
        installations = tuple(
            self._installation(candidate_key, candidate, running.get(candidate_key, []), origins.get(candidate_key, []))
            for candidate_key, candidate in accepted
        )
        unmatched = tuple(
            f"{path} (origin : {origin})"
            for origin_key, folders in sorted(origins.items())
            if origin_key not in owned_keys
            for path, origin in folders
        )
        return DiscoveryResult(
            observed_at=self._clock.now(),
            installations=installations,
            rejected=tuple(rejected),
            unmatched_data_folders=unmatched,
        )

    # ------------------------------------------------------------------------------------------------ internals

    def _data_folders_by_origin(self) -> dict[str, list[tuple[str, str]]]:
        """Every data folder under the configured root that names an installation in its ``origin.txt``: ``common`` and ``community`` do not."""
        found: dict[str, list[tuple[str, str]]] = {}
        root = self._config.data_root
        if not root:
            return found
        for entry in self._files.list_directory(root):
            if not entry.is_dir:
                continue
            path = str(PureWindowsPath(root) / entry.name)
            origin = self._files.read_origin(path)
            if origin:
                found.setdefault(key_of(origin), []).append((path, origin))
        return found

    def _installation(
        self,
        candidate_key: str,
        candidate: _Candidate,
        instances: list[RunningTerminal],
        owned_folders: list[tuple[str, str]],
    ) -> Installation:
        install = candidate.display
        folders = [
            self._data_folder(path, data_folder_id(path), portable=False, origin=origin)
            for path, origin in sorted(owned_folders, key=lambda item: item[0].lower())
        ]
        if any(instance.portable for instance in instances):
            folders.append(self._data_folder(install, portable_id(install), portable=True, origin=None))
        exe = str(PureWindowsPath(install) / EXE_NAME)
        return Installation(
            install_path=install,
            exe_path=exe,
            version=self._files.file_version(exe),
            sources=candidate.sources,
            running=tuple(instances),
            data_folders=tuple(sorted(folders, key=lambda item: item.terminal_id)),
        )

    def _data_folder(self, path: str, terminal_id: str, *, portable: bool, origin: str | None) -> DataFolder:
        mql5 = PureWindowsPath(path) / "MQL5"
        experts = mql5 / "Experts"
        entries = self._files.list_directory(str(experts))
        return DataFolder(
            terminal_id=terminal_id,
            path=normalize(path),
            portable=portable,
            origin=normalize(origin) if origin else None,
            experts_present=self._files.is_dir(str(experts)),
            presets_present=self._files.is_dir(str(mql5 / "Presets")),
            files_present=self._files.is_dir(str(mql5 / "Files")),
            link_file_present=self._files.is_file(str(mql5 / "Files" / "tradingos_agent.token")),
            eas=tuple(_ea_of(entry) for entry in entries if entry.is_dir and entry.name.lower() in OUR_EA_NAMES),
            third_party_experts=tuple(
                sorted(
                    (entry.name for entry in entries if _is_third_party_ex5(entry)),
                    key=str.casefold,
                )[:MAX_LISTED]
            ),
        )


def _ea_of(entry: DirEntry) -> EaInstall:
    return EaInstall(
        kind=EaInstallKind.JUNCTION if entry.is_link else EaInstallKind.DIRECTORY,
        name=entry.name,
        target=entry.link_target,
    )


def _is_third_party_ex5(entry: DirEntry) -> bool:
    name = entry.name.lower()
    return not entry.is_dir and name.endswith(".ex5") and not name.startswith("tradingos")
