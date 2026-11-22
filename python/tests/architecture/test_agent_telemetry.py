"""Agent 1.14 (ADR 0040): read-only telemetry in the ``hello``. Structural checks on the MQL5 source, like ``test_execution_agent.py``.

What 1.14 adds is a *report*: the protocol, the chart, the instance, the terminal build, the initialisation state and the protections actually loaded. It adds no input, no
command, no order path; the mode and its ceiling stay compile-time constants set to OBSERVE; nothing secret is reported. A test fails if any of that moves.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parents[3] / "tools" / "mt5-execution-agent" / "TradingOsAgent.mq5"

TELEMETRY_FIELDS = {
    "protocolVersion",
    "chart",
    "instanceId",
    "terminalBuild",
    "initState",
    "initIssues",
    "localProtections",
}
HELLO_BEFORE_114 = {
    "version", "type", "accountId", "time", "agentId", "symbol", "broker", "server", "orderTypes", "minVolume", "maxVolume",
    "volumeStep", "fillingMode", "stopsLevelPoints", "mode", "agentVersion", "serverUtcOffsetMinutes", "token", "capabilities",
    "buildId", "modeCeiling", "identity", "expectedAccountId", "tradeMode", "marginMode", "fifoClose", "leverage", "currency",
    "terminalTradeAllowed", "expertTradeAllowed", "accountTradeExpert", "accountTradeAllowed", "tradable", "closable", "halted",
    "attachedExperts",
}  # fmt: skip
PROTECTION_FIELDS = {
    "maxVolumePerOrder", "maxOpenPositions", "maxSlippagePoints", "maxSpread", "allowedSymbols", "deadManSeconds", "pendingMaxMinutes",
}  # fmt: skip


@pytest.fixture(scope="module")
def source() -> str:
    return AGENT.read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    start = re.search(rf"^[A-Za-z_][\w \*]*\b{name}\s*\([^)]*\)\s*\n\{{", source, re.MULTILINE)
    assert start, f"function {name} not found"
    depth, index = 0, start.end() - 1
    for index in range(start.end() - 1, len(source)):
        depth += source[index] == "{"
        depth -= source[index] == "}"
        if depth == 0:
            break
    return source[start.start() : index + 1]


def json_keys(text: str) -> set[str]:
    return set(re.findall(r'\\"(\w+)\\":', text))


def test_the_version_is_115_in_both_places_and_the_protocol_is_still_one(source: str) -> None:
    # 1.15 (ADR 0041) changes the answer to a command (a refusal code), not the message set: the protocol stays 1
    assert re.search(r'#property version\s+"1\.15"', source)
    assert re.search(r'#define AGENT_VERSION\s+"1\.15"', source)
    assert re.search(r"#define PROTOCOL_VERSION\s+1\b", source)


def test_the_hello_says_exactly_what_it_said_plus_the_fields_of_the_table_and_nothing_else(source: str) -> None:
    keys = json_keys(function_body(source, "SendHello")) - {"symbol", "period"} | {"symbol"}
    assert keys - {"symbol", "period"} <= (HELLO_BEFORE_114 | TELEMETRY_FIELDS), sorted(
        keys - HELLO_BEFORE_114 - TELEMETRY_FIELDS - {"symbol", "period"}
    )
    for field in TELEMETRY_FIELDS:
        assert field in keys, field


def test_the_telemetry_never_reports_a_secret_a_magic_number_or_the_lists_of_logins(source: str) -> None:
    names = (
        "PeriodLabel",
        "InstanceId",
        "ResolveInitState",
        "InitIssuesJson",
        "AllowedSymbolsJson",
        "MaxSpreadJson",
        "LocalProtectionsJson",
    )
    for name in names:
        body = function_body(source, name)
        assert not re.search(r"Token|token|Password|password|Logins|Magic|magic", body), name
    assert json_keys(function_body(source, "LocalProtectionsJson")) == PROTECTION_FIELDS


def test_the_telemetry_can_place_nothing_and_change_nothing(source: str) -> None:
    for name in (
        "PeriodLabel",
        "InstanceId",
        "ResolveInitState",
        "InitIssuesJson",
        "AllowedSymbolsJson",
        "MaxSpreadJson",
        "LocalProtectionsJson",
    ):
        body = function_body(source, name)
        assert not re.search(
            r"OrderSend|OrderCheck|Trade|PositionClose|PositionModify|GlobalVariableSet|FileWrite|ObjectCreate|SymbolSelect",
            body,
        ), name


def test_no_input_was_added_or_removed_by_the_telemetry(source: str) -> None:
    inputs = re.findall(r"^input\s+\w+\s+(\w+)\s*=", source, re.MULTILINE)
    assert len(inputs) == len(set(inputs))
    assert "InpAccountId" in inputs and "InpMagicNumber" in inputs
    assert not [
        name for name in inputs if "Telemetry" in name or ("Report" in name and name != "InpReportReplayMinutes")
    ]


def test_an_initialisation_that_is_degraded_keeps_the_agent_loaded(source: str) -> None:
    """Degraded is reported, never fatal: the init function still returns success after it (the only refusals are the magic number and the instance lock)."""
    init = function_body(source, "OnInit")
    assert init.count("INIT_FAILED") == 1 and init.count("INIT_PARAMETERS_INCORRECT") == 1
    assert "ResolveInitState();" in init and init.rstrip().endswith("}") and "return INIT_SUCCEEDED;" in init
