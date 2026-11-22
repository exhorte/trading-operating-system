"""Fakes and builders for the MetaTrader 5 side of the launcher tests (ADR 0038 § 6, ADR 0039 § 4 — I3). Nothing here touches the machine: the
files port is an in-memory tree, the programs port a list, the process table the one of the other launcher tests. Paths are Windows paths held in
strings, so the logic is tested the same on any machine."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import PureWindowsPath

from tests.unit.launcher.support import T0, FakeProcessTable, proc
from trading_os.launcher.mt5.model import ChartSpec, DeclaredTerminal, Mt5Config
from trading_os.launcher.mt5.ports import DirEntry, ProgramEntry
from trading_os.shared.time import ManualClock

INSTALL = r"C:\Program Files\MetaTrader 5"
EXE = INSTALL + r"\terminal64.exe"
PROGRAM_FILES = r"C:\Program Files"
DATA_ROOT = r"C:\Users\trader\AppData\Roaming\MetaQuotes\Terminal"
DATA_ID = "D0E8209F77C8CF37AD8BF550E51FF075"
DATA = DATA_ROOT + "\\" + DATA_ID
EA_TARGET = r"C:\Ebrain\trading\04_code\tools\mt5-execution-agent"


def key(path: str) -> str:
    return str(PureWindowsPath(path)).rstrip("\\").lower()


def config() -> Mt5Config:
    return Mt5Config(program_roots=(PROGRAM_FILES, r"C:\Program Files (x86)"), data_root=DATA_ROOT)


class FakeMt5Files:
    """A tree in memory. Every read is recorded, so a test can say *what was looked at* — and that nothing else was."""

    def __init__(self) -> None:
        self.directories: dict[str, list[DirEntry]] = {}
        self.files: set[str] = set()
        self.origins: dict[str, str] = {}
        self.versions: dict[str, str] = {}
        self.asked: list[tuple[str, str]] = []
        self.experts: dict[str, bool] = {}

    def add_dir(self, path: str, *entries: DirEntry) -> None:
        self.directories.setdefault(key(path), [])
        self.directories[key(path)].extend(entries)

    def add_file(self, path: str, version: str | None = None) -> None:
        self.files.add(key(path))
        if version:
            self.versions[key(path)] = version

    # --- the port
    def is_dir(self, path: str) -> bool:
        self.asked.append(("is_dir", path))
        return key(path) in self.directories

    def is_file(self, path: str) -> bool:
        self.asked.append(("is_file", path))
        return key(path) in self.files

    def list_directory(self, path: str) -> list[DirEntry]:
        self.asked.append(("list_directory", path))
        return list(self.directories.get(key(path), []))

    def read_origin(self, data_folder: str) -> str | None:
        self.asked.append(("read_origin", data_folder))
        return self.origins.get(key(data_folder))

    def file_version(self, path: str) -> str | None:
        self.asked.append(("file_version", path))
        return self.versions.get(key(path))

    def experts_enabled(self, data_folder: str) -> bool | None:
        self.asked.append(("experts_enabled", data_folder))
        return self.experts.get(key(data_folder))


class FakePrograms:
    def __init__(self, entries: Iterable[ProgramEntry] = ()) -> None:
        self._entries = list(entries)

    def programs(self) -> list[ProgramEntry]:
        return list(self._entries)


def folder(name: str) -> DirEntry:
    return DirEntry(name=name, is_dir=True)


def file_entry(name: str) -> DirEntry:
    return DirEntry(name=name, is_dir=False)


def junction(name: str, target: str) -> DirEntry:
    return DirEntry(name=name, is_dir=True, is_link=True, link_target=target)


def add_install(files: FakeMt5Files, path: str = INSTALL, version: str = "5.0.0.6230") -> None:
    files.add_dir(path)
    files.add_file(path + r"\terminal64.exe", version)


def add_data_folder(
    files: FakeMt5Files,
    data_id: str = DATA_ID,
    *,
    origin: str = INSTALL,
    experts: Iterable[DirEntry] = (),
    presets: bool = False,
    link_file: bool = False,
    root: str = DATA_ROOT,
) -> str:
    path = root + "\\" + data_id
    files.add_dir(root, folder(data_id))
    files.add_dir(path)
    files.origins[key(path)] = origin
    files.add_dir(path + r"\MQL5")
    files.add_dir(path + r"\MQL5\Experts", *experts)
    files.add_dir(path + r"\MQL5\Files")
    if presets:
        files.add_dir(path + r"\MQL5\Presets")
    if link_file:
        files.add_file(path + r"\MQL5\Files\tradingos_agent.token")
    return path


def standard_machine() -> tuple[FakeMt5Files, FakePrograms, FakeProcessTable]:
    """This workstation, as audited on 2026-11-06: one installation (registered and found in Program Files), one data folder carrying our EA
    through a junction and a third-party EA, no ``Presets`` folder, a terminal running with no argument."""
    files = FakeMt5Files()
    add_install(files)
    files.add_dir(PROGRAM_FILES, folder("MetaTrader 5"), folder("Docker"), folder("nodejs"))
    add_data_folder(
        files,
        experts=[
            folder("Advisors"),
            junction("TradingOsAgent", EA_TARGET),
            file_entry("Ultimate_ICT_Gold_Scalper_v4.0.ex5"),
            file_entry("Ultimate_ICT_Gold_Scalper_v4.0.mq5"),
        ],
        link_file=True,
    )
    files.add_dir(DATA_ROOT, folder("Common"), folder("Community"))  # no origin.txt in those two: not terminals
    programs = FakePrograms([ProgramEntry(display_name="MetaTrader 5", locations=(INSTALL,))])
    table = FakeProcessTable([proc(1872, name="terminal64.exe", command_line=f'"{EXE}" ', executable=EXE)])
    return files, programs, table


def clock() -> ManualClock:
    return ManualClock(T0)


def declared(**changes: object) -> DeclaredTerminal:
    """A complete, valid declaration for the Exness demo of this workstation; ``changes`` override single fields."""
    base: dict[str, object] = {
        "account_id": "exness-486046157",
        "expected_login": "486046157",
        "chart": ChartSpec(symbol="XAUUSDm", period="M5"),
        "magic": 486046,
        "allowed_symbols": ("XAUUSDm", "EURUSDm"),
        "provider": "EXNESS",
        "product": "EXNESS_STANDARD",
    }
    base.update(changes)
    return DeclaredTerminal(**base)  # type: ignore[arg-type]
