"""What the launcher *starts* (ADR 0038, I2): a detached process with its output in a log file, and the few Docker commands the database needs.

Fixed argument lists, no shell. Nothing here ends a process: that is ``process_control.py``, and only that.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from trading_os.launcher.ports import CommandRunner, SpawnError

SAFE_FILE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
DATABASE_USER = "tradingos"  # docker-compose.yml
DATABASE_NAME = "tradingos"


class SubprocessSpawner:
    """Starts a process that outlives the launcher: no window, no stdin, output appended to ``log_path``. It keeps its own (hidden) console,
    which is how ``process_control`` can later ask it to stop politely (Ctrl+Break). It leads a process group of its own — the group id is its
    pid, which is what the request is addressed to. (Windows switches Ctrl+C off for such a group; Ctrl+Break, which is what is used, stays.)"""

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        """The process also leaves the Windows *job* of whoever launched it (``CREATE_BREAKAWAY_FROM_JOB``): a terminal, an IDE or an assistant session
        that closes its job kills everything still inside it, and an autonomous core must survive the window that started it. A job that forbids
        breaking away refuses the flag (access denied): the process is then started inside it, as before, rather than not at all."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        base = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        attempts = (base | breakaway, base) if breakaway else (base,)
        last_error: OSError | None = None
        for flags in attempts:
            try:
                with log_path.open("ab") as log:
                    process = subprocess.Popen(
                        list(args),
                        cwd=cwd,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        creationflags=flags,
                        close_fds=True,
                    )
                return process.pid
            except PermissionError as error:  # the job forbids breaking away: try again inside it
                last_error = error
            except OSError as error:
                raise SpawnError(str(error)) from error
        raise SpawnError(str(last_error))


class DockerActionsCli:
    def __init__(self, runner: CommandRunner) -> None:
        self._runner = runner

    def start_container(self, name: str) -> bool:
        return self._runner.run(["docker", "start", name], timeout=60).returncode == 0

    def create_database(self, repo_root: Path) -> bool:
        """As ``start.ps1`` does: the volume is declared external in the compose file, so it must already exist — nothing creates an empty one."""
        return (
            self._runner.run(["docker", "compose", "up", "-d", "timescaledb"], timeout=180, cwd=repo_root).returncode
            == 0
        )

    def stop_container(self, name: str) -> bool:
        return self._runner.run(["docker", "stop", name], timeout=90).returncode == 0

    def dump_database(self, container: str, destination: Path) -> bool:
        """``pg_dump -Fc`` inside the container, copied out, then the temporary copy inside is removed. True only when the file is there."""
        if not SAFE_FILE_NAME.match(destination.name):
            return False
        inside = f"/tmp/{destination.name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        dumped = self._runner.run(
            ["docker", "exec", container, "pg_dump", "-Fc", "-U", DATABASE_USER, "-f", inside, DATABASE_NAME],
            timeout=600,
        )
        if dumped.returncode != 0:
            return False
        copied = self._runner.run(["docker", "cp", f"{container}:{inside}", str(destination)], timeout=300)
        self._runner.run(["docker", "exec", container, "rm", "-f", inside], timeout=30)
        return copied.returncode == 0 and destination.exists() and destination.stat().st_size > 0
