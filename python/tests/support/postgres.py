"""A throwaway PostgreSQL for the database tests.

Resolution order — and if none works the tests **fail** with the reason (they never skip silently, never run "on empty"):

1. ``TRADINGOS_TEST_DATABASE_URL`` — an admin-capable URL of a server you provide (CI service, a container); each test gets
   its own database on it. The database named ``tradingos`` is refused outright: tests never touch the real one.
2. a private cluster started here from locally installed PostgreSQL binaries (``initdb`` + ``pg_ctl``) in a temp
   directory, on a free loopback port, with trust authentication. It has nothing to do with any PostgreSQL service the
   machine is already running, and is stopped and deleted at the end of the session.

Binaries are looked for in ``TRADINGOS_PG_BIN``, on ``PATH``, then in the usual Windows/Linux install directories.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

REAL_DATABASE_NAME = "tradingos"


class NoPostgres(RuntimeError):
    pass


@dataclass
class Server:
    admin_url: str  # URL of the maintenance database ("postgres"), with rights to CREATE DATABASE

    def url_for(self, database: str) -> str:
        base, _, query = self.admin_url.partition("?")
        root = base.rsplit("/", 1)[0]
        return f"{root}/{database}" + (f"?{query}" if query else "")

    def create_database(self, name: str, template: str | None = None) -> str:
        assert name != REAL_DATABASE_NAME, "the tests never create or touch the real database"
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            query = sql.SQL("CREATE DATABASE {} ").format(sql.Identifier(name))
            if template:
                query += sql.SQL("TEMPLATE {}").format(sql.Identifier(template))
            conn.execute(query)
        return self.url_for(name)

    def drop_database(self, name: str) -> None:
        assert name != REAL_DATABASE_NAME
        with contextlib.suppress(Exception), psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def _find_binaries() -> Path | None:
    candidates: list[Path] = []
    if os.environ.get("TRADINGOS_PG_BIN"):
        candidates.append(Path(os.environ["TRADINGOS_PG_BIN"]))
    found = shutil.which("initdb")
    if found:
        candidates.append(Path(found).parent)
    for root in (Path("C:/Program Files/PostgreSQL"), Path("/usr/lib/postgresql")):
        if root.is_dir():
            for version in sorted(root.iterdir(), reverse=True):
                candidates.append(version / "bin")
    exe = ".exe" if os.name == "nt" else ""
    for folder in candidates:
        if (folder / f"initdb{exe}").is_file() and (folder / f"pg_ctl{exe}").is_file():
            return folder
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class EphemeralCluster:
    def __init__(self, bin_dir: Path) -> None:
        exe = ".exe" if os.name == "nt" else ""
        self._initdb = str(bin_dir / f"initdb{exe}")
        self._pg_ctl = str(bin_dir / f"pg_ctl{exe}")
        self.root = Path(tempfile.mkdtemp(prefix="tradingos-pg-"))
        self.data = self.root / "data"
        self.port = _free_port()

    def start(self) -> Server:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            [self._initdb, "-D", str(self.data), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"],
            check=True,
            capture_output=True,
            creationflags=flags,
            timeout=120,
        )
        options = (
            f"-p {self.port} -c listen_addresses=127.0.0.1 -c fsync=off -c synchronous_commit=off "
            "-c full_page_writes=off -c max_connections=60"
        )
        # Not capture_output: the server inherits pg_ctl's handles, so a pipe would stay open until the server exits
        # and subprocess.run would never return. The server's own log goes to a file.
        subprocess.run(
            [self._pg_ctl, "-D", str(self.data), "-o", options, "-l", str(self.root / "server.log"), "-w", "start"],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            timeout=120,
        )
        return Server(f"postgresql://postgres@127.0.0.1:{self.port}/postgres")

    def stop(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            [self._pg_ctl, "-D", str(self.data), "-m", "immediate", "-w", "stop"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            timeout=60,
        )
        for _ in range(10):  # Windows may still hold a file for a moment
            try:
                shutil.rmtree(self.root)
                return
            except OSError:
                time.sleep(0.3)
        shutil.rmtree(self.root, ignore_errors=True)


@contextlib.contextmanager
def postgres_server() -> Iterator[Server]:
    url = os.environ.get("TRADINGOS_TEST_DATABASE_URL")
    if url:
        yield Server(url)
        return
    bin_dir = _find_binaries()
    if bin_dir is None:
        raise NoPostgres(
            "no PostgreSQL for the database tests: set TRADINGOS_TEST_DATABASE_URL (admin URL of a throwaway server) "
            "or TRADINGOS_PG_BIN (folder with initdb and pg_ctl), or install PostgreSQL"
        )
    cluster = EphemeralCluster(bin_dir)
    try:
        yield cluster.start()
    finally:
        cluster.stop()


def unique_name(prefix: str = "tradingos_test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"
