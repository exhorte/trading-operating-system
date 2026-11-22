"""The real (Windows) adapters of the MetaTrader 5 read ports (ADR 0038 § 6, I3). They look at the file system and at the list of installed
programs. They write nothing, create nothing, delete nothing; the registry is opened for reading only.

The version of an executable is read from its own resources through ``version.dll`` (no PowerShell, no interpolated path).
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path, PureWindowsPath
from typing import Any

import httpx

from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.mt5.model import (
    CenterFacts,
    TerminalEntry,
    TerminalSnapshot,
    TerminalVerdict,
    VerdictCondition,
)
from trading_os.launcher.mt5.ports import DirEntry, ProgramEntry
from trading_os.launcher.ports import CommandRunner, ProbeError

MAX_ORIGIN_BYTES = 4096
MAX_CONFIG_BYTES = 1 << 20
PROBE_TIMEOUT_S = 90.0
WORKER_MODULE = "trading_os.infrastructure.mt5.worker"  # the core's read-only worker, spoken to over its JSON lines — never imported here
MAX_ENTRIES = 5000
UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
FIXED_FILE_INFO_SIGNATURE = 0xFEEF04BD


class LocalMt5Files:
    def is_dir(self, path: str) -> bool:
        try:
            return Path(path).is_dir()
        except OSError:
            return False

    def is_file(self, path: str) -> bool:
        try:
            return Path(path).is_file()
        except OSError:
            return False

    def list_directory(self, path: str) -> list[DirEntry]:
        """The entries of a folder, by name. A missing or unreadable folder is an empty one. A junction is reported as a link with its target."""
        try:
            with os.scandir(path) as scanned:
                entries = list(scanned)[:MAX_ENTRIES]
        except OSError:
            return []
        found: list[DirEntry] = []
        for entry in entries:
            try:
                is_link = entry.is_junction() or entry.is_symlink()
                is_dir = entry.is_dir()
            except OSError:
                continue
            target: str | None = None
            if is_link:
                try:
                    target = os.readlink(entry.path).removeprefix(
                        "\\\\?\\"
                    )  # the extended-length prefix is not a path to show
                except OSError:
                    target = None
            found.append(DirEntry(name=entry.name, is_dir=is_dir, is_link=is_link, link_target=target))
        return sorted(found, key=lambda item: item.name.casefold())

    def read_origin(self, data_folder: str) -> str | None:
        """The installation a terminal says owns this data folder: the first line of ``origin.txt``. Anything odd (too big, binary) is no answer."""
        try:
            with (Path(data_folder) / "origin.txt").open("rb") as handle:
                raw = handle.read(MAX_ORIGIN_BYTES + 1)
        except OSError:
            return None
        if not raw or len(raw) > MAX_ORIGIN_BYTES:
            return None
        text = _decode(raw)
        if text is None:
            return None
        lines = text.strip().splitlines()
        first = lines[0].strip() if lines else ""
        return first or None

    def file_version(self, path: str) -> str | None:
        return _file_version(path)

    def experts_enabled(self, data_folder: str) -> bool | None:
        """The one value read from MetaTrader's configuration file: whether expert advisors may run. Nothing else of the file is returned or kept."""
        try:
            with (Path(data_folder) / "config" / "common.ini").open("rb") as handle:
                raw = handle.read(MAX_CONFIG_BYTES)
        except OSError:
            return None
        text = _decode(raw)
        if text is None:
            return None
        section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip().lower()
            elif section == "experts" and "=" in stripped:
                key, _, value = stripped.partition("=")
                if key.strip().lower() == "enabled":
                    return value.strip() == "1"
        return None


def _decode(raw: bytes) -> str | None:
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16")
        elif raw.startswith(b"\xef\xbb\xbf"):
            text = raw.decode("utf-8-sig")
        elif b"\x00" in raw:
            text = raw.decode("utf-16-le")
        else:
            text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if any(ord(char) < 9 for char in text) else text


class _FixedFileInfo(ctypes.Structure):
    _fields_ = (
        ("signature", wintypes.DWORD),
        ("struct_version", wintypes.DWORD),
        ("file_version_ms", wintypes.DWORD),
        ("file_version_ls", wintypes.DWORD),
        ("product_version_ms", wintypes.DWORD),
        ("product_version_ls", wintypes.DWORD),
        ("file_flags_mask", wintypes.DWORD),
        ("file_flags", wintypes.DWORD),
        ("file_os", wintypes.DWORD),
        ("file_type", wintypes.DWORD),
        ("file_subtype", wintypes.DWORD),
        ("file_date_ms", wintypes.DWORD),
        ("file_date_ls", wintypes.DWORD),
    )


def _file_version(path: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        library = ctypes.WinDLL("version", use_last_error=True)
        size_of = library.GetFileVersionInfoSizeW
        size_of.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        size_of.restype = wintypes.DWORD
        read = library.GetFileVersionInfoW
        read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID]
        read.restype = wintypes.BOOL
        query = library.VerQueryValueW
        query.argtypes = [
            wintypes.LPCVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.UINT),
        ]
        query.restype = wintypes.BOOL
        size = size_of(path, None)
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not read(path, 0, size, buffer):
            return None
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not query(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < ctypes.sizeof(
            _FixedFileInfo
        ):
            return None
        info = ctypes.cast(pointer, ctypes.POINTER(_FixedFileInfo)).contents
        if info.signature != FIXED_FILE_INFO_SIGNATURE:
            return None
        ms, ls = info.file_version_ms, info.file_version_ls
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (OSError, ValueError, AttributeError):
        return None


class WindowsInstalledPrograms:
    """The list of installed programs (the three « Uninstall » keys), opened for reading only."""

    def programs(self) -> list[ProgramEntry]:
        if sys.platform != "win32":
            return []
        import winreg

        views = (
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_CURRENT_USER, 0),
        )
        found: list[ProgramEntry] = []
        for hive, view in views:
            try:
                root = winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with root:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    entry = _program(winreg, root, name)
                    if entry is not None:
                        found.append(entry)
        return found


def _program(winreg: object, root: object, subkey: str) -> ProgramEntry | None:
    try:
        key = winreg.OpenKey(root, subkey, 0, winreg.KEY_READ)  # type: ignore[attr-defined]
    except OSError:
        return None
    with key:
        values: dict[str, str] = {}
        for value in ("DisplayName", "InstallLocation", "DisplayIcon", "UninstallString"):
            try:
                data, _kind = winreg.QueryValueEx(key, value)  # type: ignore[attr-defined]
            except OSError:
                continue
            if isinstance(data, str) and data.strip():
                values[value] = data.strip()
    name = values.get("DisplayName")
    if not name:
        return None
    locations: list[str] = []
    if "InstallLocation" in values:
        locations.append(values["InstallLocation"].strip('"'))
    for command in ("DisplayIcon", "UninstallString"):
        if command in values:
            folder = _folder_of_command(values[command])
            if folder:
                locations.append(folder)
    return ProgramEntry(display_name=name, locations=tuple(dict.fromkeys(locations)))


def _folder_of_command(text: str) -> str | None:
    """The folder of the program a registry value names: ``"C:\\x\\a.exe",0`` or ``C:\\x\\a.exe /uninstall`` give ``C:\\x``."""
    text = text.strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        candidate = text[1:end] if end > 0 else text[1:]
    else:
        lower = text.lower()
        cut = lower.find(".exe")
        candidate = text[: cut + 4] if cut >= 0 else text.split(",")[0]
    candidate = candidate.split(",")[0].strip()
    if not candidate:
        return None
    parent = str(PureWindowsPath(candidate).parent)
    return parent if parent not in {".", ""} else None


class WorkerPositionsProbe:
    """A read-only look at a running terminal, through the core's own read worker: the protocol it speaks has a white list of read functions and no order
    function (a test of the core fails if one ever appears). It attaches to the terminal that is open — it is only ever called for one that is running —
    asks four questions and goes. The account holder's name never leaves the worker; only the login is kept, in memory, to be compared."""

    def __init__(self, runner: CommandRunner, config: LauncherConfig) -> None:
        self._runner = runner
        self._config = config

    def read(self, exe_path: str) -> TerminalSnapshot:
        requests = [
            {"id": 1, "fn": "initialize", "kwargs": {"path": exe_path, "timeout": 30000}},
            {"id": 2, "fn": "account_info"},
            {"id": 3, "fn": "positions_total"},
            {"id": 4, "fn": "orders_total"},
            {"id": 5, "fn": "shutdown"},
        ]
        result = self._runner.run(
            [str(self._config.venv_python), "-m", WORKER_MODULE],
            timeout=PROBE_TIMEOUT_S,
            cwd=self._config.core_cwd,
            stdin="".join(json.dumps(request, separators=(",", ":")) + "\n" for request in requests),
        )
        answers: dict[int, dict[str, Any]] = {}
        for line in result.stdout.splitlines():
            try:
                answer = json.loads(line)
            except ValueError:
                continue
            if isinstance(answer, dict) and isinstance(answer.get("id"), int):
                answers[answer["id"]] = answer
        if not answers.get(1, {}).get("ok") or answers[1].get("result") is not True:
            raise ProbeError("MetaTrader 5 n'a pas répondu à la lecture des positions : le terminal n'a pas pu être lu")
        positions, orders = answers.get(3, {}), answers.get(4, {})
        account = answers.get(2, {}).get("result")
        login = account.get("login") if answers.get(2, {}).get("ok") and isinstance(account, dict) else None
        return TerminalSnapshot(
            login=str(login) if isinstance(login, int | str) and str(login).isdigit() else None,
            positions=positions["result"] if positions.get("ok") and isinstance(positions.get("result"), int) else None,
            orders=orders["result"] if orders.get("ok") and isinstance(orders.get("result"), int) else None,
        )


class HttpCenterView:
    """What the core says of a terminal's agent, from ``GET /api/system/mt5/terminals``. The core's access key is held privately by this adapter — it is read from the
    settings the core itself loads, sent in the request header, and never printed, stored or put in a model. A core that cannot be asked (down, refusing,
    answering nonsense) is ``reachable=False``: that is neither a hello nor its absence."""

    def __init__(self, base_url: str, access_key: str | None, origin: str, *, timeout_s: float = 5.0) -> None:
        self._url = base_url.rstrip("/") + "/api/system/mt5/terminals"
        self._headers = {"Origin": origin, **({"Authorization": f"Bearer {access_key}"} if access_key else {})}
        self._timeout = timeout_s

    def terminal_facts(self, entry: TerminalEntry) -> CenterFacts:
        try:
            response = httpx.get(self._url, headers=self._headers, timeout=self._timeout)
        except httpx.HTTPError:
            return CenterFacts(reachable=False)
        if response.status_code != 200:
            return CenterFacts(reachable=False)
        try:
            items = response.json()
        except ValueError:
            return CenterFacts(reachable=False)
        if not isinstance(items, list):
            return CenterFacts(reachable=False)
        for item in items:
            if (
                isinstance(item, dict)
                and isinstance(item.get("terminal"), dict)
                and item["terminal"].get("terminalId") == entry.terminal_id
            ):
                return _facts_of(item)
        return CenterFacts(reachable=True, hello_received=False)


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _facts_of(item: dict[str, Any]) -> CenterFacts:
    readiness = _dict(item.get("readiness"))
    agent = _dict(item.get("agent"))
    authorization = _dict(readiness.get("executionAuthorization"))
    conditions = tuple(
        VerdictCondition(
            code=str(c.get("code", "")),
            label=str(c.get("label", "")),
            light=str(c.get("light", "")),
            detail=str(c.get("detail", "")),
        )
        for c in readiness.get("conditions", [])
        if isinstance(c, dict)
    )
    age = agent.get("heartbeatAgeS")
    reasons = ", ".join(_strings(authorization.get("reasons")))
    return CenterFacts(
        reachable=True,
        hello_received=bool(item.get("helloReceived")),
        verdict=TerminalVerdict(
            verdict=readiness.get("verdict") if isinstance(readiness.get("verdict"), str) else None,
            red_codes=_strings(readiness.get("redCodes")),
            pending_codes=_strings(readiness.get("pendingCodes")),
            warning_codes=_strings(readiness.get("warningCodes")),
            header_code=readiness.get("headerCode") if isinstance(readiness.get("headerCode"), str) else None,
            heartbeat_age_s=float(age) if isinstance(age, int | float) else None,
            agent_version=agent.get("agentVersion") if isinstance(agent.get("agentVersion"), str) else None,
            execution_authorization=("AUTORISÉE" if authorization.get("allowed") else f"BLOQUÉE — {reasons}")
            if authorization
            else None,
            conditions=conditions,
        ),
    )
