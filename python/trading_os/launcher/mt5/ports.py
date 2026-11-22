"""What the launcher may *look at* on a MetaTrader 5 machine (ADR 0038 § 6). Every method reads; none writes, starts or deletes anything.

``read_origin`` is the only way to read a file's content, and it reads ``origin.txt`` — the line a terminal writes to say which installation owns a
data folder. Nothing else is ever read: not ``common.ini``, not a profile, not the token file (``is_file`` only says whether it is there).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from trading_os.launcher.mt5.model import CenterFacts, TerminalEntry, TerminalSnapshot


@dataclass(frozen=True)
class DirEntry:
    name: str
    is_dir: bool
    is_link: bool = False  # a junction or a symbolic link
    link_target: str | None = None


@dataclass(frozen=True)
class ProgramEntry:
    """One entry of the list of installed programs: its name, and the folders it may be installed in (each one is checked before it is believed)."""

    display_name: str
    locations: tuple[str, ...]


class Mt5FilesPort(Protocol):
    def is_dir(self, path: str) -> bool: ...

    def is_file(self, path: str) -> bool: ...

    def list_directory(self, path: str) -> list[DirEntry]: ...

    def read_origin(self, data_folder: str) -> str | None: ...

    def file_version(self, path: str) -> str | None: ...

    def experts_enabled(self, data_folder: str) -> bool | None:
        """Whether MetaTrader lets expert advisors run — the one setting read from its configuration file, nothing else of it. ``None`` = not said."""
        ...


class InstalledProgramsPort(Protocol):
    def programs(self) -> list[ProgramEntry]: ...


class PositionsProbe(Protocol):
    """A read-only look at a **running** terminal: the login it is on, its open positions and its pending orders. It places, checks and changes nothing.
    Raises ``ProbeError`` when the terminal cannot be read: a caller fails closed on that."""

    def read(self, exe_path: str) -> TerminalSnapshot: ...


class CenterView(Protocol):
    """What the core says of the agent of a terminal (ADR 0039 § 8). Never raises: a core that cannot be asked is ``reachable=False``."""

    def terminal_facts(self, entry: TerminalEntry) -> CenterFacts: ...
