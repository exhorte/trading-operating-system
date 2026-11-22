"""The compatibility table EA <-> core (ADR 0039 § 7): pure data and one pure function, shared by the launcher (before it copies a build) and the core
(at the ``hello``). Nothing here reads a file or a socket."""

from __future__ import annotations

import ast
from pathlib import Path

import trading_os.shared.agent_compat as compat
from trading_os.shared.agent_compat import Compatibility, CompatResult, assess_agent

CAPABILITIES_113 = ("ping", "halt", "dead_man", "limit", "modify", "close", "cancel")


def test_agent_113_is_compatible_with_one_warning_the_protocol_is_not_reported() -> None:
    result = assess_agent("1.13", CAPABILITIES_113, None)
    assert result.result is CompatResult.COMPATIBLE_WITH_WARNINGS
    assert result.codes == ("PROTOCOL_VERSION_UNREPORTED",)
    assert result.compatible


def test_agent_114_reporting_the_supported_protocol_is_fully_compatible() -> None:
    result = assess_agent("1.14", CAPABILITIES_113, 1)
    assert result == Compatibility(result=CompatResult.COMPATIBLE, codes=(), reasons=())
    assert result.compatible


def test_a_hello_with_no_agent_version_is_incompatible() -> None:
    for missing in (None, "", "   "):
        result = assess_agent(missing, CAPABILITIES_113, None)
        assert result.result is CompatResult.INCOMPATIBLE
        assert "AGENT_VERSION_MISSING" in result.codes
        assert not result.compatible


def test_an_unreadable_agent_version_is_incompatible() -> None:
    result = assess_agent("one point thirteen", CAPABILITIES_113, None)
    assert result.result is CompatResult.INCOMPATIBLE
    assert "AGENT_VERSION_UNREADABLE" in result.codes


def test_an_envelope_the_core_does_not_speak_is_incompatible() -> None:
    result = assess_agent("1.13", CAPABILITIES_113, None, envelope=2)
    assert result.result is CompatResult.INCOMPATIBLE
    assert "ENVELOPE_UNSUPPORTED" in result.codes
    assert assess_agent("1.13", CAPABILITIES_113, None, envelope=1).compatible


def test_a_protocol_outside_the_supported_range_is_incompatible() -> None:
    result = assess_agent("1.14", CAPABILITIES_113, 99)
    assert result.result is CompatResult.INCOMPATIBLE
    assert "PROTOCOL_VERSION_UNSUPPORTED" in result.codes


def test_a_missing_dead_man_capability_is_a_warning_not_a_refusal() -> None:
    """Whether the core must refuse to arm such an agent is decision (5) of the HANDOFF: this table does not make it."""
    result = assess_agent("1.10", ("ping", "halt"), None)
    assert result.result is CompatResult.COMPATIBLE_WITH_WARNINGS
    assert "CAPABILITY_DEAD_MAN_MISSING" in result.codes
    assert result.compatible


def test_capabilities_that_are_not_reported_are_a_warning_and_never_assumed() -> None:
    result = assess_agent("1.13", None, None)
    assert "CAPABILITIES_UNREPORTED" in result.codes
    assert "CAPABILITY_DEAD_MAN_MISSING" not in result.codes


def test_every_code_has_a_reason_in_french() -> None:
    result = assess_agent("", None, 99, envelope=3)
    assert len(result.reasons) == len(result.codes) >= 3
    assert all(reason and reason[0].isalpha() for reason in result.reasons)


def test_the_table_is_dated_and_has_no_input_output() -> None:
    assert compat.TABLE_DATE
    source = Path(compat.__file__).read_text(encoding="utf-8")
    imported = {
        alias.name if isinstance(node, ast.Import) else (node.module or "")
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [None])  # type: ignore[list-item]
    }
    assert not {
        name
        for name in imported
        if name.split(".")[0] in {"socket", "subprocess", "httpx", "os", "pathlib", "trading_os"}
    }
