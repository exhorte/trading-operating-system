"""The execution agent (MQL5) is not Python, but what it guarantees is part of what the core relies on — so the source is read here,
structurally, and a refactor cannot silently weaken it:

* the one ``OrderSend`` of the repository sits in ``ExecuteOrder``, behind a mode check that is its first statement, and the mode is a
  compiled constant that nothing assigns (ADR 0010: a physical barrier, not a switch);
* the dead-man switch: a NEW order is refused (``DEAD_MAN``) unless the core has pinged recently, and only a ``control.ping`` — never an
  order, never any other line — counts as proof of life. A refusal only: it opens nothing and closes nothing.

No terminal is needed; compiling is a separate check (MetaEditor, ``/compile``) that a developer runs when the file changes.
"""

from __future__ import annotations

import re

import pytest

from trading_os.app.config import REPO_ROOT
from trading_os.domain.execution.reasons import RejectCode

SOURCE = REPO_ROOT / "tools" / "mt5-execution-agent" / "TradingOsAgent.mq5"


def strip_comments_and_strings(text: str, *, keep_strings: bool = False) -> str:
    """The code as the compiler reads it: comments gone, and — unless ``keep_strings`` — string literals emptied (their braces and
    keywords are not code)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        two = text[i : i + 2]
        if two == "//":
            while i < n and text[i] != "\n":
                i += 1
        elif two == "/*":
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif text[i] == '"':
            start = i
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
            out.append(text[start:i] if keep_strings else '""')
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def body_of(code: str, name: str) -> str:
    """The text between the braces of function ``name`` (comment- and string-free source)."""
    match = re.search(rf"\b(?:void|bool|string|int|double|long|ulong|datetime)\s+{name}\s*\([^)]*\)\s*\{{", code)
    assert match, f"function {name} not found"
    depth, start = 1, match.end()
    for i in range(start, len(code)):
        depth += {"{": 1, "}": -1}.get(code[i], 0)
        if depth == 0:
            return code[start:i]
    raise AssertionError(f"function {name} is not closed")


@pytest.fixture(scope="module")
def raw() -> str:
    assert SOURCE.exists(), f"the execution agent source is missing: {SOURCE}"
    return SOURCE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def code(raw: str) -> str:
    return strip_comments_and_strings(raw)


class TestTheOrderPathIsBarred:
    def test_there_is_exactly_one_order_send_and_it_is_in_execute_order(self, code: str) -> None:
        assert len(re.findall(r"\bOrderSend(?:Async)?\s*\(", code)) == 1
        assert re.search(r"\bOrderSend\s*\(", body_of(code, "ExecuteOrder"))

    def test_its_first_statement_returns_unless_the_mode_is_confirm(self, code: str) -> None:
        first = re.match(
            r"\s*if\s*\(\s*g_mode\s*!=\s*MODE_CONFIRM\s*\)\s*\{(?P<then>.*?)\}",
            body_of(code, "ExecuteOrder"),
            re.DOTALL,
        )
        assert first, "ExecuteOrder must start with the mode check"
        assert "return" in first.group("then")

    def test_the_mode_and_its_ceiling_are_compiled_constants_that_nothing_assigns(self, code: str) -> None:
        assert re.search(r"\bconst\s+ExecutionMode\s+g_mode\s*=\s*MODE_OBSERVE\s*;", code)
        assert re.search(r"\bconst\s+ExecutionMode\s+g_mode_ceiling\s*=\s*MODE_OBSERVE\s*;", code)
        for name in ("g_mode", "g_mode_ceiling"):
            assert len(re.findall(rf"\b{name}\s*=(?!=)", code)) == 1, (
                f"{name} is assigned somewhere besides its declaration"
            )


class TestTheDeadManSwitch:
    def test_an_order_is_validated_against_the_core_liveness_before_anything_else(self, code: str) -> None:
        body = body_of(code, "ValidateOrderCommand")
        assert re.match(
            r"\s*string\s+dead\s*=\s*DeadManReason\(\)\s*;\s*if\s*\(\s*dead\s*!=\s*\"\"\s*\)\s*\{\s*return\s+dead\s*;\s*\}",
            body,
        )

    def test_the_refusal_is_typed_so_the_core_reads_its_code(self, raw: str, code: str) -> None:
        reasons = re.findall(r'return\s+"(DEAD_MAN:[^"]*)"', raw[raw.index("string DeadManReason()") :])
        assert len(reasons) == 2 and all(r.startswith("DEAD_MAN: ") for r in reasons)
        # the core takes everything before the first colon as the code of the refusal (services/execution.py)
        assert RejectCode("DEAD_MAN") is RejectCode.DEAD_MAN
        assert {r.split(":", 1)[0] for r in reasons} == {RejectCode.DEAD_MAN.value}

    def test_the_limit_can_be_loosened_but_not_switched_off(self, code: str) -> None:
        assert re.search(
            r"return\s*\(\s*InpDeadManSeconds\s*>=\s*5\s*&&\s*InpDeadManSeconds\s*<=\s*600\s*\)\s*\?\s*InpDeadManSeconds\s*:\s*30\s*;",
            body_of(code, "DeadManSeconds"),
        )

    def test_a_connection_starts_without_proof_of_life(self, code: str) -> None:
        assert re.search(r"\bg_last_ping_ms\s*=\s*0\s*;", body_of(code, "ConnectToCore"))
        body = body_of(code, "DeadManReason")
        assert re.search(r"if\s*\(\s*g_last_ping_ms\s*==\s*0\s*\)\s*\{\s*return", body)

    def test_only_a_ping_is_proof_of_life(self, raw: str, code: str) -> None:
        assignments = re.findall(r"\bg_last_ping_ms\s*=(?!=)\s*([^;]+);", code)
        assert sorted(assignments) == sorted(["0", "0", "GetTickCount64()"]), (
            assignments
        )  # declaration, connection reset, the ping
        handler = body_of(strip_comments_and_strings(raw, keep_strings=True), "HandleMessage")
        ping = re.search(r'type\s*==\s*"control\.ping"\s*\)\s*\{(?P<body>.*?)\}', handler, re.DOTALL)
        assert ping and re.search(r"\bg_last_ping_ms\s*=\s*GetTickCount64\(\)\s*;", ping.group("body"))

    def test_the_agent_announces_the_capability_so_the_core_can_tell_a_build_that_lacks_it(self, raw: str) -> None:
        assert '\\"dead_man\\"' in raw[raw.index('"\\"capabilities\\":[') :][:120]
