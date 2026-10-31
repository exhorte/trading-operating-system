"""Process-wide logging configuration (console, masked)."""

from __future__ import annotations

import logging
import sys

from trading_os.shared.logging.redaction import RedactingFormatter

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """Route everything through one masked console handler.

    uvicorn's access log is *not* used by the app (it prints the query string, which carries the WebSocket
    token); its other loggers are rerouted here so they are masked too.
    """
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingFormatter(_FORMAT))
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs every request URL at INFO, and a FRED URL carries the API key in its query string (the masker would
    # catch it, but a secret that is never written is better than one that is masked).
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
