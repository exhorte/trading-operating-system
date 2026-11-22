"""The preset (``.set``) of a terminal (ADR 0039 §§ 4 and 5, I5): what the agent is started with — as pure functions.

The preset says only what Exhorte **declared** about the terminal (the login it must be on, its magic number, the symbols the agent may trade) and
what the agent's own **source** allows: every key it writes is an ``input`` the source declares, every other input keeps the default the source gives.
It never carries a token (the token is not an input: it stays in ``MQL5\\Files``), a password, or a list of logins an order may reach — those lists
are always written empty, whatever is declared; filling them is a decision of Exhorte's, made in MetaTrader.

The format is the one MetaTrader writes: ``Name=value`` lines, UTF-16 little-endian with a byte-order mark and CRLF line ends.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from trading_os.launcher.mt5.model import FIELD_LABELS, DeclaredTerminal

_INPUT = re.compile(r"^\s*input\s+(\w+)\s+(\w+)\s*=\s*(.+?)\s*;\s*(?://.*)?$", re.MULTILINE)
_LOGIN_LISTS = re.compile(
    r"Logins$"
)  # the inputs that say on which logins an order may reach the broker: always empty here
LOOPBACK = "127.0.0.1"


class PresetRefused(Exception):
    """A preset that is not made, with every reason (French: shown to a person)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class AgentInput:
    name: str
    type: str
    default: str


@dataclass(frozen=True)
class Preset:
    values: tuple[tuple[str, str], ...]


def parse_inputs(source: str) -> list[AgentInput]:
    """The ``input`` declarations of the agent's source, in order. A default is read without its quotes and without its trailing comment."""
    found = []
    for kind, name, default in _INPUT.findall(source):
        value = default.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        found.append(AgentInput(name=name, type=kind, default=value))
    return found


def build_preset(declared: DeclaredTerminal, inputs: Sequence[AgentInput], *, core_port: int) -> Preset:
    problems = [
        f"{FIELD_LABELS[name]} non déclaré"
        for name in ("expected_login", "magic", "allowed_symbols", "chart")
        if getattr(declared, name) in (None, ())
    ]
    names = {item.name for item in inputs}
    problems.extend(
        f"l'agent n'a pas l'entrée {name} : sans elle, le preset ne peut pas le lier à votre déclaration"
        for name in ("InpAccountId", "InpMagicNumber", "InpAllowedSymbolsCsv")
        if name not in names
    )
    if problems:
        raise PresetRefused(problems)
    chosen = {
        "InpAccountId": declared.expected_login or "",
        "InpMagicNumber": str(declared.magic),
        "InpAllowedSymbolsCsv": ",".join(declared.allowed_symbols),
        "InpCoreHost": LOOPBACK,
        "InpCorePort": str(core_port),
    }
    values = []
    for item in inputs:
        if _LOGIN_LISTS.search(item.name):
            value = ""
        else:
            value = chosen.get(item.name, item.default)
        if "\r" in value or "\n" in value:
            raise PresetRefused([f"la valeur de {item.name} contient un saut de ligne"])
        values.append((item.name, value))
    return Preset(values=tuple(values))


def render_set(preset: Preset) -> bytes:
    text = "".join(f"{name}={value}\r\n" for name, value in preset.values)
    return b"\xff\xfe" + text.encode("utf-16-le")
