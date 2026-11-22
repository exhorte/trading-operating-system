"""The real (Windows) adapters of the launcher's **read** ports (ADR 0038, I1). What starts or stops something lives elsewhere
(``actions.py`` starts, ``process_control.py`` is the only module that ends a process).

PowerShell and the Docker CLI are driven through a ``CommandRunner`` so that tests feed them canned output. Every command is a fixed argument
list — no shell, nothing interpolated but integers — and whatever cannot be read **fails closed**: an unreadable process table raises
``ProbeError`` instead of pretending that nothing runs. The one process these adapters can end is the probe they started themselves, when
it exceeds its timeout (``subprocess.run`` does it); no process of the system is ever ended.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from trading_os.launcher.model import ContainerInfo, CoreHealth, Listener, Mt5WorkersFacts, ProcessInfo
from trading_os.launcher.ports import CommandResult, CommandRunner, ProbeError
from trading_os.shared.time import parse_iso

POWERSHELL = "powershell.exe"
TIMEOUT_NOT_ANSWERING = 124
EXECUTABLE_NOT_FOUND = 127


class SubprocessRunner:
    """Runs a command without a shell and without a console window, and turns every failure into a result."""

    def run(
        self, args: Sequence[str], *, timeout: float, cwd: Path | None = None, stdin: str | None = None
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                list(args),
                cwd=cwd,
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return CommandResult(TIMEOUT_NOT_ANSWERING, "", f"no answer after {timeout:g} s")
        except OSError as error:
            return CommandResult(EXECUTABLE_NOT_FOUND, "", str(error))
        return CommandResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def _json(result: CommandResult, *, what: str, empty_is: Any = None) -> Any:
    """The JSON a command printed. PowerShell may put a byte-order mark in front of it."""
    if result.returncode != 0:
        raise ProbeError(f"{what} : la commande a échoué (code {result.returncode}) {result.stderr.strip()[:200]}")
    text = result.stdout.lstrip("﻿").strip()
    if not text:
        if empty_is is not None:
            return empty_is
        raise ProbeError(f"{what} : la commande n'a rien renvoyé")
    try:
        return json.loads(text)
    except ValueError as error:
        raise ProbeError(f"{what} : sortie illisible ({error.__class__.__name__})") from error


def _rows(document: Any, *, what: str) -> list[dict[str, Any]]:
    if isinstance(document, dict):
        document = [document]
    if not isinstance(document, list):
        raise ProbeError(f"{what} : ni une liste ni un objet")
    return [row for row in document if isinstance(row, dict)]


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_iso(value)
    except ValueError:
        return None


def _count(value: object) -> int | None:
    """A count the core reported, or ``None``: a boolean is not a count, and a negative number is not either."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _workers(value: object) -> Mt5WorkersFacts | None:
    if not isinstance(value, dict):
        return None
    spawned, ended, alive = _count(value.get("spawned")), _count(value.get("ended")), _count(value.get("alive"))
    if spawned is None or ended is None or alive is None:
        return None
    return Mt5WorkersFacts(spawned=spawned, ended=ended, alive=alive)


def _pilot_active(value: object) -> bool | None:
    """``autopilot.active`` of the core's health: exactly a boolean, or not said — never coerced (a « 1 » or a « yes » is not a fact)."""
    if not isinstance(value, dict):
        return None
    active = value.get("active")
    return active if isinstance(active, bool) else None


_ENCODING = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8"

_PROCESSES_SCRIPT = (
    f"{_ENCODING}; "
    "$rows = @(Get-CimInstance Win32_Process | ForEach-Object { [pscustomobject]@{ "
    "pid = [int]$_.ProcessId; parentPid = [int]$_.ParentProcessId; name = $_.Name; executable = $_.ExecutablePath; "
    "commandLine = $_.CommandLine; "
    "createdAt = $(if ($_.CreationDate) { $_.CreationDate.ToUniversalTime().ToString('o') } else { $null }) } }); "
    "ConvertTo-Json -InputObject $rows -Compress"
)


def _listeners_script(ports: Sequence[int]) -> str:
    wanted = ",".join(str(port) for port in ports)
    return (
        f"{_ENCODING}; "
        "$rows = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.LocalPort -in @({wanted}) }} | "
        "ForEach-Object { [pscustomobject]@{ address = $_.LocalAddress; port = [int]$_.LocalPort; pid = [int]$_.OwningProcess } }); "
        "ConvertTo-Json -InputObject $rows -Compress"
    )


class WindowsProcessTable:
    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def processes(self) -> list[ProcessInfo]:
        what = "table des processus"
        result = self._runner.run(self._powershell(_PROCESSES_SCRIPT), timeout=40)
        found: list[ProcessInfo] = []
        for row in _rows(_json(result, what=what), what=what):
            pid = row.get("pid")
            if not isinstance(pid, int) or isinstance(pid, bool):
                continue
            parent = row.get("parentPid")
            found.append(
                ProcessInfo(
                    pid=pid,
                    parent_pid=parent if isinstance(parent, int) and not isinstance(parent, bool) else 0,
                    name=str(row.get("name") or ""),
                    executable=row.get("executable") if isinstance(row.get("executable"), str) else None,
                    command_line=row.get("commandLine") if isinstance(row.get("commandLine"), str) else "",
                    created_at=_time(row.get("createdAt")),
                )
            )
        return found

    def listeners(self, ports: Sequence[int]) -> list[Listener]:
        for port in ports:
            if not isinstance(port, int) or isinstance(port, bool):
                raise TypeError(f"a port is an integer, not {port!r}")
        what = "ports à l'écoute"
        result = self._runner.run(self._powershell(_listeners_script(ports)), timeout=30)
        found: list[Listener] = []
        for row in _rows(_json(result, what=what, empty_is=[]), what=what):
            listening_port, owner = row.get("port"), row.get("pid")
            if isinstance(listening_port, int) and isinstance(owner, int):
                found.append(Listener(address=str(row.get("address") or ""), port=listening_port, pid=owner))
        return found

    @staticmethod
    def _powershell(script: str) -> list[str]:
        return [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script]


class DockerCli:
    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def available(self) -> bool:
        """Does the daemon answer? Asked twice: on a busy machine (a full test run, Docker Desktop waking up) the first ``docker info`` can
        miss its deadline, and a false « unavailable » blocks the start of a database that is perfectly healthy. Not installed: one try."""
        for _ in range(2):
            result = self._runner.run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return True
            if result.returncode == EXECUTABLE_NOT_FOUND:
                return False
        return False

    def container(self, name: str) -> ContainerInfo | None:
        result = self._runner.run(["docker", "inspect", name], timeout=20)
        if result.returncode != 0:
            return None  # « No such object » — the container does not exist
        rows = _rows(_json(result, what=f"docker inspect {name}"), what=f"docker inspect {name}")
        if not rows:
            return None
        row = rows[0]
        state = _mapping(row.get("State"))
        health = _mapping(state.get("Health")).get("Status")
        ports = _mapping(_mapping(row.get("NetworkSettings")).get("Ports"))
        published: set[int] = set()
        for bindings in ports.values():
            for binding in bindings if isinstance(bindings, list) else []:
                host_port = _mapping(binding).get("HostPort")
                if isinstance(host_port, str) and host_port.isdigit():
                    published.add(int(host_port))
        return ContainerInfo(
            name=str(row.get("Name") or name).lstrip("/"),
            status=str(state.get("Status") or "unknown"),
            health=health if isinstance(health, str) else None,
            host_ports=tuple(sorted(published)),
        )

    def port_holders(self, port: int) -> list[str]:
        result = self._runner.run(
            ["docker", "ps", "--filter", f"publish={int(port)}", "--format", "{{.Names}}"], timeout=20
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class HttpxProbe:
    """GET requests on the loopback and nothing else; the environment's proxy settings are ignored."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout: float = 3.0) -> None:
        self._transport = transport
        self._timeout = timeout

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=self._timeout, follow_redirects=False, trust_env=False)

    def _get(self, url: str) -> httpx.Response | None:
        """One GET, and one more after a transport error. The first request to ``next dev`` can outlast the wait while it compiles (measured: 5 s on a
        loaded machine, 1 s the next time); a false « no answer » would be reported as a problem. A response — whatever its code — is an answer
        and is never asked again."""
        for _ in range(2):
            try:
                with self._client() as client:
                    return client.get(url)
            except httpx.HTTPError:
                continue
        return None

    def core_health(self, url: str) -> CoreHealth | None:
        response = self._get(url)
        if response is None or response.status_code != 200:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        database = body.get("database")
        status, version = body.get("status"), body.get("version")
        if not isinstance(database, dict) or not isinstance(database.get("up"), bool):
            return None
        if not isinstance(status, str) or not isinstance(version, str):
            return None
        findings = body.get("findings")
        mode = body.get("executionMode")
        return CoreHealth(
            status=status,
            version=version,
            database_up=database["up"],
            findings=len(findings) if isinstance(findings, list) else 0,
            started_at=_time(body.get("startedAt")),
            agents_connected=_count(body.get("agentsConnected")),
            mt5_workers=_workers(body.get("mt5Workers")),
            execution_mode=mode if isinstance(mode, str) and mode else None,
            autopilot_active=_pilot_active(body.get("autopilot")),
        )

    def http_status(self, url: str) -> int | None:
        response = self._get(url)
        return response.status_code if response is not None else None


class LocalEnvironment:
    def path_exists(self, path: Path) -> bool:
        return path.exists()

    def which(self, name: str) -> str | None:
        return shutil.which(name)
