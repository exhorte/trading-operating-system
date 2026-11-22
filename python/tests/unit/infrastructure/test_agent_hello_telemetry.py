"""What an agent 1.14 says of itself in its ``hello`` (ADR 0040 § 1 and § 3): read-only telemetry, all of it optional, nothing of it ever filled in by the core.

A 1.13 sends none of these fields and is accepted exactly as before; a 1.14 gives the chart, the instance, the protocol, the initialisation state and the
protections it actually loaded. Unknown keys are still ignored (``extra="ignore"`` is not loosened), and nothing secret can reach the status.
"""

from __future__ import annotations

import re
from typing import Any

from trading_os.domain.execution.agent import AgentStatus
from trading_os.infrastructure.mt5.ea_link import build_status
from trading_os.infrastructure.mt5.wire import AgentHello

BASE: dict[str, Any] = {
    "type": "agent.hello",
    "accountId": "1000001",
    "agentId": "mt5-execution-agent-1001",
    "agentVersion": "1.13",
}
FULL: dict[str, Any] = {
    **BASE,
    "agentVersion": "1.14",
    "protocolVersion": 1,
    "chart": {"symbol": "XAUUSDm", "period": "M5"},
    "instanceId": "D0E8209F77C8CF37AD8BF550E51FF075",
    "terminalBuild": 6230,
    "initState": "READY",
    "localProtections": {
        "maxVolumePerOrder": 1.0,
        "maxOpenPositions": 2,
        "maxSlippagePoints": 10,
        "maxSpread": {"EURUSDm": 0.01, "XAUUSDm": 10.0},
        "allowedSymbols": ["XAUUSDm", "EURUSDm"],
        "deadManSeconds": 30,
        "pendingMaxMinutes": 60,
    },
}


def status(payload: dict[str, Any]) -> AgentStatus:
    return build_status(AgentHello.model_validate(payload), None)


def test_a_113_hello_is_accepted_and_reports_none_of_the_telemetry() -> None:
    result = status(BASE)
    assert result.agent_version == "1.13"
    assert result.protocol_version is None and result.chart_symbol is None and result.chart_period is None
    assert result.instance_id is None and result.terminal_build is None and result.init_state is None
    assert result.init_issues == [] and result.local_protections is None


def test_a_114_hello_gives_the_chart_the_instance_the_protocol_and_the_loaded_protections() -> None:
    result = status(FULL)
    assert (result.protocol_version, result.chart_symbol, result.chart_period) == (1, "XAUUSDm", "M5")
    assert result.instance_id == "D0E8209F77C8CF37AD8BF550E51FF075" and result.terminal_build == 6230
    assert result.init_state == "READY" and result.init_issues == []
    protections = result.local_protections
    assert protections is not None
    assert protections.dead_man_seconds == 30 and protections.max_open_positions == 2
    assert protections.allowed_symbols == ["XAUUSDm", "EURUSDm"] and protections.max_spread == {
        "EURUSDm": 0.01,
        "XAUUSDm": 10.0,
    }


def test_a_degraded_initialisation_carries_its_issues() -> None:
    result = status({**FULL, "initState": "DEGRADED", "initIssues": ["SYMBOL_NOT_AVAILABLE:XAUUSDm"]})
    assert result.init_state == "DEGRADED" and result.init_issues == ["SYMBOL_NOT_AVAILABLE:XAUUSDm"]


def test_a_partial_report_stays_partial_and_nothing_is_supposed() -> None:
    result = status({**BASE, "chart": {"symbol": "EURUSDm", "period": "H1"}})
    assert result.chart_symbol == "EURUSDm" and result.instance_id is None and result.local_protections is None


def test_unknown_keys_are_still_ignored() -> None:
    result = status({**FULL, "somethingNew": {"a": 1}, "localProtections": {**FULL["localProtections"], "extra": 5}})
    assert result.agent_version == "1.14"


def test_the_status_has_no_field_that_could_carry_a_secret() -> None:
    secret = re.compile(r"token|password|passwd|secret|credential|api_?key|magic", re.IGNORECASE)
    fields = set(AgentStatus.model_fields)
    assert not {name for name in fields if secret.search(name) and name != "magic_number"}


def test_an_instance_id_is_a_name_not_a_path() -> None:
    """ADR 0040: the full data path holds the Windows user name; only its last segment travels."""
    assert "\\" not in (status(FULL).instance_id or "") and "/" not in (status(FULL).instance_id or "")
