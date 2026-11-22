"""Which EA builds the core accepts (ADR 0039 § 7): a table of minimums, dated, and one pure function.

It lives in ``shared`` so that the launcher (which asks *before* it copies a build to a terminal) and the core (which asks at the ``hello``) use
the same answer without either importing the other. It reads nothing: it is given what the build or the ``hello`` says and answers.

Three results. ``COMPATIBLE``: nothing to say. ``COMPATIBLE_WITH_WARNINGS``: it works, and something is not known or not recommended (a 1.13 does not
report a protocol version; an agent without the ``dead_man`` capability is accepted today — whether the core must refuse to arm it is a separate
decision, not this table's). ``INCOMPATIBLE``: nothing continues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

TABLE_DATE = "2026-11-12"
ENVELOPE_VERSION = 1  # the wire envelope of ``protocol.md``
SUPPORTED_PROTOCOLS = (1,)  # what a 1.14 agent reports as ``protocolVersion``; a 1.13 reports none
RECOMMENDED_CAPABILITY = "dead_man"

_VERSION = re.compile(r"^\d+\.\d+$")

REASONS = {
    "ENVELOPE_UNSUPPORTED": "l'enveloppe des messages de cet agent n'est pas celle que le cœur comprend",
    "AGENT_VERSION_MISSING": "l'agent ne dit pas sa version",
    "AGENT_VERSION_UNREADABLE": "la version de l'agent n'a pas la forme « majeure.mineure »",
    "PROTOCOL_VERSION_UNSUPPORTED": "la version de protocole de l'agent n'est pas prise en charge par le cœur",
    "PROTOCOL_VERSION_UNREPORTED": "l'agent ne rapporte pas sa version de protocole (attendu d'un 1.13 : rapportée dès le 1.14)",
    "CAPABILITIES_UNREPORTED": "l'agent ne rapporte pas ses capacités",
    "CAPABILITY_DEAD_MAN_MISSING": "l'agent n'annonce pas la capacité « dead_man » (protection locale contre la perte du cœur)",
}
_FATAL = ("ENVELOPE_UNSUPPORTED", "AGENT_VERSION_MISSING", "AGENT_VERSION_UNREADABLE", "PROTOCOL_VERSION_UNSUPPORTED")


class CompatResult(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    COMPATIBLE_WITH_WARNINGS = "COMPATIBLE_WITH_WARNINGS"
    INCOMPATIBLE = "INCOMPATIBLE"


@dataclass(frozen=True)
class Compatibility:
    result: CompatResult
    codes: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return self.result is not CompatResult.INCOMPATIBLE


def assess_agent(
    agent_version: str | None,
    capabilities: tuple[str, ...] | list[str] | None,
    protocol_version: int | None,
    *,
    envelope: int | None = ENVELOPE_VERSION,
) -> Compatibility:
    """What the table says of a build (its manifest) or of an agent that has just said ``hello``."""
    codes: list[str] = []
    if envelope is not None and envelope != ENVELOPE_VERSION:
        codes.append("ENVELOPE_UNSUPPORTED")
    version = (agent_version or "").strip()
    if not version:
        codes.append("AGENT_VERSION_MISSING")
    elif not _VERSION.match(version):
        codes.append("AGENT_VERSION_UNREADABLE")
    if protocol_version is None:
        codes.append("PROTOCOL_VERSION_UNREPORTED")
    elif protocol_version not in SUPPORTED_PROTOCOLS:
        codes.append("PROTOCOL_VERSION_UNSUPPORTED")
    if capabilities is None:
        codes.append("CAPABILITIES_UNREPORTED")
    elif RECOMMENDED_CAPABILITY not in capabilities:
        codes.append("CAPABILITY_DEAD_MAN_MISSING")
    if any(code in _FATAL for code in codes):
        result = CompatResult.INCOMPATIBLE
    elif codes:
        result = CompatResult.COMPATIBLE_WITH_WARNINGS
    else:
        result = CompatResult.COMPATIBLE
    return Compatibility(result=result, codes=tuple(codes), reasons=tuple(REASONS[code] for code in codes))
