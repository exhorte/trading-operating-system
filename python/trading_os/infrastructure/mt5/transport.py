"""How the core talks to a terminal: a ``Mt5Transport`` runs one call at a time against a read worker.

* ``SubprocessTransport`` — the real thing: a child process (``worker.py``) per terminal, JSON lines over its pipes.
  A call that does not answer in time **kills** the worker (a native call stuck in the terminal must never freeze the core)
  and the next call starts a fresh one. Calls are serialised: the package is not re-entrant.
* ``InProcessTransport`` — the same protocol against an in-memory module (``FakeMt5``), for tests and the simulated mode.

No request is ever logged with its arguments: ``initialize``/``login`` carry a password. Only the function name is.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sys
from typing import Any, Protocol

from trading_os.infrastructure.mt5.protocol import WorkerError, dispatch, dumps, encode_argument
from trading_os.shared.errors import Unavailable
from trading_os.shared.logging.redaction import redact

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
SLOW_CALLS = {"initialize": 60.0, "login": 60.0}  # the terminal may have to start, or reach the broker
MAX_NOISE_LINES = 50  # stdout lines that are not our JSON (a library printing) tolerated while waiting for an answer


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
    def __init__(
        self, *, backend: str = "real", default_timeout: float = DEFAULT_TIMEOUT, python: str | None = None
    ) -> None:
        self._backend = backend
        self._default_timeout = default_timeout
        self._python = python or sys.executable
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self.restarts = 0

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _ensure(self) -> asyncio.subprocess.Process:
        if self._process is not None and self._process.returncode is None:
            return self._process
        if self._process is not None:
            self.restarts += 1
        self._process = await asyncio.create_subprocess_exec(
            self._python,
            "-m",
            "trading_os.infrastructure.mt5.worker",
            "--backend",
            self._backend,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._process))
        return self._process

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        with contextlib.suppress(Exception):
            async for line in process.stderr:
                logger.debug("mt5 worker: %s", redact(line.decode("utf-8", errors="replace").rstrip()))

    async def _kill(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=5)
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None

    async def call(self, fn: str, *args: Any, timeout: float | None = None, **kwargs: Any) -> Any:
        deadline = timeout if timeout is not None else SLOW_CALLS.get(fn, self._default_timeout)
        async with self._lock:
            process = await self._ensure()
            assert process.stdin is not None and process.stdout is not None
            self._next_id += 1
            request_id = self._next_id
            line = dumps(
                {
                    "id": request_id,
                    "fn": fn,
                    "args": [encode_argument(a) for a in args],
                    "kwargs": {k: encode_argument(v) for k, v in kwargs.items()},
                }
            )
            try:
                process.stdin.write(line.encode("utf-8") + b"\n")
                await process.stdin.drain()
                response = await asyncio.wait_for(self._read_response(process, request_id), timeout=deadline)
            except TimeoutError:
                await self._kill()
                raise Unavailable(
                    f"MT5 call {fn!r} did not answer within {deadline:g}s — worker restarted", code="mt5_timeout"
                ) from None
            except (ConnectionError, BrokenPipeError, OSError, EOFError):
                await self._kill()
                raise Unavailable(f"MT5 worker died during {fn!r}", code="mt5_worker_died") from None
        return _unwrap(response)

    async def _read_response(self, process: asyncio.subprocess.Process, request_id: int) -> dict[str, Any]:
        assert process.stdout is not None
        for _ in range(MAX_NOISE_LINES):
            raw = await process.stdout.readline()
            if not raw:
                raise EOFError("worker closed its output")
            try:
                response = json.loads(raw)
            except json.JSONDecodeError:
                continue  # something printed to stdout that is not ours
            if isinstance(response, dict) and response.get("id") == request_id:
                return response
        raise EOFError("worker produced only noise")

    async def close(self) -> None:
        async with self._lock:
            process = self._process
            if process is not None and process.returncode is None and process.stdin is not None:
                with contextlib.suppress(Exception):
                    process.stdin.write(dumps({"id": -1, "fn": "shutdown"}).encode("utf-8") + b"\n")
                    await process.stdin.drain()
                    await asyncio.wait_for(process.wait(), timeout=2)
            await self._kill()
