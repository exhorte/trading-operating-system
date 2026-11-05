"""How the core talks to a terminal: a ``Mt5Transport`` runs one call at a time against a read worker.

* ``SubprocessTransport`` — the real thing: a child process (``worker.py``) per terminal, JSON lines over its pipes.
  A call that does not answer in time, or is **cancelled** from outside (a job's deadline, a shutdown), **kills** the worker
  and everything it started (a native call stuck in the terminal must never freeze the core, and must never outlive its
  caller — ADR 0037); the next call starts a fresh one. Calls are serialised: the package is not re-entrant.
* ``InProcessTransport`` — the same protocol against an in-memory module (``FakeMt5``), for tests and the simulated mode.

No request is ever logged with its arguments: ``initialize``/``login`` carry a password. Only the function name is.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import subprocess
import sys
import threading
import weakref
from typing import Any, Protocol

from trading_os.infrastructure.mt5.protocol import WorkerError, dispatch, dumps, encode_argument
from trading_os.shared.errors import Unavailable
from trading_os.shared.logging.redaction import redact

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
SLOW_CALLS = {"initialize": 60.0, "login": 60.0}  # the terminal may have to start, or reach the broker
MAX_NOISE_LINES = 50  # stdout lines that are not our JSON (a library printing) tolerated while waiting for an answer
REAP_PATIENCE_S = 10.0  # how long the core waits for a worker to be gone before it goes on (and says so)


class WorkerLedger:
    """How many MT5 worker processes this core has started and ended (ADR 0037) — a measurement for the health, which nothing decides on.

    A worker is *alive* from its start until the core ends it, so one the core let go of without ending stays counted: that is how a
    leak shows. Expected: one per connected account, one more while a reconnection is in flight."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ended_once: weakref.WeakSet[subprocess.Popen[bytes]] = weakref.WeakSet()
        self.spawned = 0
        self.ended = 0

    @property
    def alive(self) -> int:
        return self.spawned - self.ended

    def started(self) -> None:
        with self._lock:
            self.spawned += 1

    def end(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            if process not in self._ended_once:  # a worker is ended once, however many paths reach it
                self._ended_once.add(process)
                self.ended += 1


WORKERS = WorkerLedger()


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """End the worker and everything it started. On Windows a venv's ``python.exe`` is a launcher that starts the real interpreter as a
    child: killing the launcher alone leaves an interpreter behind, and one stuck in a native call never sees its pipe close."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError, OSError):
            process.kill()


class Mt5Transport(Protocol):
    async def call(self, fn: str, *args: Any, timeout: float | None = None, **kwargs: Any) -> Any: ...
    async def close(self) -> None: ...


def _unwrap(response: dict[str, Any]) -> Any:
    if response.get("ok"):
        return response.get("result")
    raise WorkerError(str(response.get("error", "unknown error")), code=str(response.get("code", "exception")))


class InProcessTransport:
    """Runs the protocol against a module-like object in this process. Results are round-tripped through JSON so that
    the code above sees exactly the shapes the subprocess would give it."""

    def __init__(self, module: Any) -> None:
        self._module = module
        self._lock = asyncio.Lock()

    async def call(self, fn: str, *args: Any, timeout: float | None = None, **kwargs: Any) -> Any:
        request = {
            "id": 0,
            "fn": fn,
            "args": [encode_argument(a) for a in args],
            "kwargs": {k: encode_argument(v) for k, v in kwargs.items()},
        }
        async with self._lock:
            response = json.loads(dumps(dispatch(self._module, json.loads(dumps(request)))))
        return _unwrap(response)

    async def close(self) -> None:
        return None


class SubprocessTransport:
    """``subprocess.Popen`` + threads, not ``asyncio.create_subprocess_exec``: psycopg's async mode refuses the Proactor
    event loop on Windows and asyncio subprocesses need it (Selector loops cannot spawn processes there). Blocking pipe
    reads run in the default executor; a stuck read is released by killing the worker, which closes its pipe."""

    def __init__(
        self, *, backend: str = "real", default_timeout: float = DEFAULT_TIMEOUT, python: str | None = None
    ) -> None:
        self._backend = backend
        self._default_timeout = default_timeout
        self._python = python or sys.executable
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self.restarts = 0

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _ensure(self) -> subprocess.Popen[bytes]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        if self._process is not None:
            self.restarts += 1
            self._reap(self._process)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console window flashing up on Windows
        process = subprocess.Popen(
            [self._python, "-m", "trading_os.infrastructure.mt5.worker", "--backend", self._backend],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=flags,
        )
        WORKERS.started()
        threading.Thread(target=self._drain_stderr, args=(process,), name="mt5-worker-stderr", daemon=True).start()
        self._process = process
        return process

    @staticmethod
    def _drain_stderr(process: subprocess.Popen[bytes]) -> None:
        assert process.stderr is not None
        with contextlib.suppress(Exception):
            for line in process.stderr:
                logger.debug("mt5 worker: %s", redact(line.decode("utf-8", errors="replace").rstrip()))

    @staticmethod
    def _reap(process: subprocess.Popen[bytes]) -> None:
        _kill_tree(process)  # first: the pipes only close once everything holding them is gone
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                with contextlib.suppress(Exception):
                    pipe.close()
        with contextlib.suppress(Exception):
            process.wait(timeout=5)
        if process.poll() is not None:
            WORKERS.end(process)
        else:  # not counted as ended: the ledger keeps showing it
            logger.warning("an MT5 worker (pid %s) could not be ended", process.pid)

    async def _kill(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            await asyncio.wait_for(asyncio.to_thread(self._reap, process), timeout=REAP_PATIENCE_S)
        except TimeoutError:
            logger.warning(
                "ending the MT5 worker (pid %s) takes more than %gs: going on without waiting",
                process.pid,
                REAP_PATIENCE_S,
            )

    @staticmethod
    def _round_trip(process: subprocess.Popen[bytes], line: bytes, request_id: int) -> dict[str, Any]:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(line + b"\n")
        process.stdin.flush()
        for _ in range(MAX_NOISE_LINES):
            raw = process.stdout.readline()
            if not raw:
                raise EOFError("worker closed its output")
            try:
                response = json.loads(raw)
            except json.JSONDecodeError:
                continue  # something printed to stdout that is not ours
            if isinstance(response, dict) and response.get("id") == request_id:
                return response
        raise EOFError("worker produced only noise")

    async def call(self, fn: str, *args: Any, timeout: float | None = None, **kwargs: Any) -> Any:
        deadline = timeout if timeout is not None else SLOW_CALLS.get(fn, self._default_timeout)
        async with self._lock:
            if fn == "shutdown" and not self.alive:
                return None  # nothing to shut down: a worker is never started only to be closed (ADR 0037)
            try:
                process = self._ensure()
            except OSError:
                raise Unavailable("MT5 worker could not be started", code="mt5_worker_died") from None
            self._next_id += 1
            request_id = self._next_id
            line = dumps(
                {
                    "id": request_id,
                    "fn": fn,
                    "args": [encode_argument(a) for a in args],
                    "kwargs": {k: encode_argument(v) for k, v in kwargs.items()},
                }
            ).encode("utf-8")
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(self._round_trip, process, line, request_id), timeout=deadline
                )
            except TimeoutError:
                await self._kill()
                raise Unavailable(
                    f"MT5 call {fn!r} did not answer within {deadline:g}s — worker restarted", code="mt5_timeout"
                ) from None
            except asyncio.CancelledError:
                # Cancelled from outside — a job's deadline, a shutdown. The answer will never be read and the worker may be stuck in a
                # native call: it ends with the call, as on a timeout. Shielded, so that a second cancellation cannot leave it half done.
                await asyncio.shield(self._kill())
                raise
            except (ConnectionError, BrokenPipeError, OSError, EOFError, ValueError):
                await self._kill()
                raise Unavailable(f"MT5 worker died during {fn!r}", code="mt5_worker_died") from None
        return _unwrap(response)

    async def close(self) -> None:
        async with self._lock:
            process = self._process
            if process is not None and process.poll() is None and process.stdin is not None:
                with contextlib.suppress(Exception):
                    process.stdin.write(dumps({"id": -1, "fn": "shutdown"}).encode("utf-8") + b"\n")
                    process.stdin.flush()
                    await asyncio.to_thread(process.wait, 2)
            await self._kill()
