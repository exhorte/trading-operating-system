"""Agent 1.15 (ADR 0041, increment 2): an agent compiled in OBSERVE no longer answers « SIMULATED ». It refuses the command with a typed code, ``AGENT_OBSERVE``.

What does not move: ``g_mode`` and ``g_mode_ceiling`` are compile-time constants set to OBSERVE, exactly one ``OrderSend`` exists and it stays the first thing ``ExecuteOrder`` guards —
those assertions live in ``test_execution_agent.py`` and are untouched. Here: the simulated answer is gone, the paper mode is gone, the refusal is documented.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
AGENT_DIR = ROOT / "tools" / "mt5-execution-agent"
SOURCES = [AGENT_DIR / "TradingOsAgent.mq5", *sorted((AGENT_DIR / "Include").glob("*.mqh"))]
PROTOCOL = ROOT / "context" / "execution" / "protocol.md"


@pytest.fixture(scope="module")
def source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in SOURCES)


def code_only(text: str) -> str:
    """The source without ``//`` comments and block comments — what the compiler reads."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def test_the_agent_is_version_115(source: str) -> None:
    main = (AGENT_DIR / "TradingOsAgent.mq5").read_text(encoding="utf-8")
    assert re.search(r'#property version\s+"1\.15"', main)
    assert re.search(r'#define AGENT_VERSION\s+"1\.15"', main)


def test_no_code_of_the_agent_answers_or_records_a_simulated_outcome(source: str) -> None:
    code = code_only(source)
    assert "SIMULATED" not in code and "SimulatedReport" not in code and "ReportSimulated" not in code


def test_the_paper_mode_is_not_in_the_agent(source: str) -> None:
    code = code_only(source)
    assert "MODE_PAPER" not in code and '"paper"' not in code


def test_an_agent_compiled_in_observe_refuses_with_a_typed_code(source: str) -> None:
    assert "AGENT_OBSERVE" in code_only(source)


def test_the_refusal_is_documented_in_the_protocol() -> None:
    assert "AGENT_OBSERVE" in PROTOCOL.read_text(encoding="utf-8")


def test_the_mode_and_its_ceiling_are_still_compile_time_constants_set_to_observe(source: str) -> None:
    code = code_only(source)
    assert re.search(r"const\s+ExecutionMode\s+g_mode\s*=\s*MODE_OBSERVE\s*;", code)
    assert re.search(r"const\s+ExecutionMode\s+g_mode_ceiling\s*=\s*MODE_OBSERVE\s*;", code)
    assert len(re.findall(r"\bOrderSend\s*\(", code)) == 1
