"""What the launcher keeps under ``var/launcher/``, read for the System Center (ADR 0039 § 8) — **read-only, tolerant, and independent of the launcher's code**.

The core never imports ``trading_os.launcher``: the two meet in two JSON files whose shape is the launcher's. This module reads only what the System Center
shows (the registry of terminals and the last events), keeps nothing it does not need, and treats a missing, unreadable or odd file as *absent* — never as a
crash and never as an empty truth: a damaged registry is reported as a problem.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from trading_os.domain.system.center import (
    DeclaredView,
    DeploymentView,
    LauncherEventView,
    RegisteredTerminal,
)
from trading_os.shared.time import parse_iso

REGISTRY_VERSION = 1
MAX_EVENT_BYTES = 2_000_000


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_iso(value)
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def read_registry(path: Path) -> tuple[list[RegisteredTerminal], str | None]:
    """The registered terminals, and a problem sentence if the file is there but cannot be read. A missing file is no terminal and no problem."""
    if not path.is_file():
        return [], None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [], f"registre des terminaux illisible : {error.__class__.__name__}"
    if not isinstance(document, dict) or document.get("version") != REGISTRY_VERSION:
        return [], "registre des terminaux d'une version inconnue ou mal formé"
    found: list[RegisteredTerminal] = []
    for item in document.get("terminals", []):
        if not isinstance(item, dict) or not _text(item.get("terminalId")):
            continue
        declared = _dict(item.get("declared"))
        chart = _dict(declared.get("chart"))
        deployment = _dict(item.get("deployment")) or None
        operation = _dict(item.get("operation"))
        state = _dict(item.get("lastState"))
        magic = declared.get("magic")
        symbols = declared.get("allowedSymbols")
        found.append(
            RegisteredTerminal(
                terminal_id=str(item["terminalId"]),
                label=_text(item.get("label")) or str(item["terminalId"]),
                install_path=_text(item.get("installPath")) or "",
                data_path=_text(item.get("dataPath")) or "",
                portable=bool(item.get("portable")),
                declared=DeclaredView(
                    account_id=_text(declared.get("accountId")),
                    expected_login=_text(declared.get("expectedLogin")),
                    chart_symbol=_text(chart.get("symbol")),
                    chart_period=_text(chart.get("period")),
                    magic=magic if isinstance(magic, int) and not isinstance(magic, bool) else None,
                    allowed_symbols=[s for s in symbols if isinstance(s, str)] if isinstance(symbols, list) else [],
                    provider=_text(declared.get("provider")),
                    product=_text(declared.get("product")),
                ),
                deployment=(
                    DeploymentView(
                        agent_version=_text(deployment.get("agentVersion")) or "",
                        deployed_at=_when(deployment.get("deployedAt")),
                        ex5_sha256=_text(deployment.get("ex5Sha256")),
                        expert_path=_text(deployment.get("expertPath")),
                    )
                    if deployment
                    else None
                ),
                operation=(_text(operation.get("kind")) if operation.get("kind") != "IDLE" else None),
                last_state=_text(state.get("state")),
                last_state_at=_when(state.get("at")),
            )
        )
    return found, None


def read_recent_events(directory: Path, limit: int = 30) -> list[LauncherEventView]:
    """The last ``limit`` events of the launcher, oldest first. The launcher masked every text before writing it; a damaged line is skipped."""
    if not directory.is_dir():
        return []
    found: list[LauncherEventView] = []
    for path in sorted(directory.glob("events-*.jsonl"), reverse=True):
        try:
            if path.stat().st_size > MAX_EVENT_BYTES:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        events: list[LauncherEventView] = []
        for line in lines:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and _text(item.get("type")):
                events.append(
                    LauncherEventView(
                        occurred_at=_when(item.get("occurredAt")),
                        type=str(item["type"]),
                        severity=_text(item.get("severity")) or "INFO",
                        instance_id=_text(item.get("instanceId")),
                        diagnostic=_text(item.get("diagnostic")) or "",
                    )
                )
        found = events + found
        if len(found) >= limit:
            break
    return found[-limit:]
