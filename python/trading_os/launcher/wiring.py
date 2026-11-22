"""What the launcher's commands share (ADR 0038 § 2): where the repository is, how to look at the processes, how to print. Kept apart from ``cli.py`` so
that the MetaTrader commands can use it without importing the command module that registers them."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from typing import Any

from trading_os.launcher.adapters import SubprocessRunner, WindowsProcessTable
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.ports import ProbeError, ProcessTable


class RealSleeper:
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def default_config() -> LauncherConfig:
    from trading_os.app.config import REPO_ROOT, get_settings

    settings = get_settings()
    return LauncherConfig(
        repo_root=REPO_ROOT,
        api_host=settings.api_host,
        api_port=settings.api_port,
        ea_link_port=settings.ea_link_port,
        db_port=int(os.environ.get("TRADINGOS_DB_PORT", "5433")),
    )


def make_process_table() -> ProcessTable:
    """Only to look at: it lists the processes, it can end none."""
    if sys.platform != "win32":
        raise ProbeError("le lanceur ne sait travailler que sous Windows")
    return WindowsProcessTable(SubprocessRunner())


def utf8_output() -> None:
    """The reports are French and are meant to be read by a person *or* captured by a wrapper: a redirected Windows Python would write the
    code page (cp1252), which nothing downstream decodes as UTF-8. A console is unaffected."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")


def print_json(document: Any) -> None:
    print(json.dumps(document, indent=2, ensure_ascii=False))
