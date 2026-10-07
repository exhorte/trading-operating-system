"""The MT5 read worker — a child process, one per terminal.

**The only module of the repository that imports ``MetaTrader5``.** It reads JSON requests on stdin, answers on stdout
(one line each), and executes nothing outside ``protocol.ALLOWED_FUNCTIONS``. Why a process:

* the package is global to its process and allows **one terminal per process** — two accounts connected at once need two
  workers;
* its calls are native and **blocking**: one that hangs must freeze neither the event loop (heartbeat, dead-man switch, the
  execution-agent link) nor the API — the parent kills and restarts a worker that does not answer in time;
* a native crash takes down the worker, not the core.

Run as ``python -m trading_os.infrastructure.mt5.worker [--backend real|fake]``. ``fake`` serves the in-memory simulated
terminal (tests and ``MT5_ENABLED=false``) through the very same protocol.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from trading_os.infrastructure.mt5.protocol import dispatch, dumps


def _load_backend(name: str) -> Any:
    if name == "fake":
        from trading_os.infrastructure.mt5.fake import FakeMt5

        return FakeMt5.default()
    import MetaTrader5 as mt5  # the one and only import of the package

    return mt5


def serve(backend: Any, stdin: Any = None, stdout: Any = None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
            response = (
                dispatch(backend, request) if isinstance(request, dict) else _bad(None, "request is not an object")
            )
        except json.JSONDecodeError:
            response = _bad(None, "unreadable request")
        stdout.write(dumps(response) + "\n")
        stdout.flush()
        if isinstance(request, dict) and request.get("fn") == "shutdown":
            break


def _bad(request_id: Any, message: str) -> dict[str, Any]:
    return {"id": request_id, "ok": False, "code": "bad_request", "error": message}


def main() -> None:
    parser = argparse.ArgumentParser(description="MT5 read-only worker")
    parser.add_argument("--backend", choices=["real", "fake"], default="real")
    options = parser.parse_args()
    backend = _load_backend(options.backend)
    serve(backend)


if __name__ == "__main__":
    main()
