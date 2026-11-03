"""The execution agent (MQL5) is not Python, but what it guarantees is part of what the core relies on — so the source is read here,
structurally, and a refactor cannot silently weaken it:

* the one ``OrderSend`` of the repository sits in ``ExecuteOrder``, behind a mode check that is its first statement, and the mode is a
  compiled constant that nothing assigns (ADR 0010: a physical barrier, not a switch). Since 1.12 (ADR 0029) every kind of command —
  market, limit, stop move, close, partial close, cancel — goes through that one function, after the same validation, and nothing
  else in any MQL5 file of the folder can send;
* the dead-man switch: a command is refused (``DEAD_MAN``) unless the core has pinged recently, and only a ``control.ping`` — never an
  order, never any other line — counts as proof of life. A refusal only: it opens nothing and closes nothing;
* the agent reads exactly the fields the core writes, and every refusal code it raises is documented in the protocol.

No terminal is needed; compiling is a separate check (MetaEditor, ``/compile`` on a copy) that a developer runs when the file changes.
"""

from __future__ import annotations

import ast
import re

import pytest

from trading_os.app.config import REPO_ROOT
from trading_os.domain.execution.reasons import RejectCode

AGENT_DIR = REPO_ROOT / "tools" / "mt5-execution-agent"
SOURCE = AGENT_DIR / "TradingOsAgent.mq5"
TRADE_REQUEST = AGENT_DIR / "Include" / "TradeRequest.mqh"
COMMAND_STORE = AGENT_DIR / "Include" / "CommandStore.mqh"
CHECK_SCRIPT = AGENT_DIR / "Scripts" / "TradingOsRequestCheck.mq5"
WIRE = REPO_ROOT / "python" / "trading_os" / "infrastructure" / "mt5" / "wire.py"
PROTOCOL = REPO_ROOT / "context" / "execution" / "protocol.md"

KINDS = {  # the wire message each handler answers → the core's function that writes it
    "execution.order": ("HandleOrderCommand", "order_line"),
    "execution.modify": ("HandleModifyCommand", "modify_line"),
    "execution.close": ("HandleCloseCommand", "close_line"),
    "execution.cancel": ("HandleCancelCommand", "cancel_line"),
}


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


def wire_keys(function: str) -> set[str]:
    """The JSON keys the core's ``wire.py`` function ``function`` writes (the string keys of the dict literal it sends)."""
    tree = ast.parse(WIRE.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function)
    return {
        key.value
        for dictionary in ast.walk(node)
        if isinstance(dictionary, ast.Dict)
        for key in dictionary.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def sources() -> dict[str, str]:
    """Every MQL5 source file of the agent folder, by path relative to it."""
    files = sorted([*AGENT_DIR.rglob("*.mq5"), *AGENT_DIR.rglob("*.mqh")])
    assert files, f"no MQL5 source under {AGENT_DIR}"
    return {str(path.relative_to(AGENT_DIR)).replace("\\", "/"): path.read_text(encoding="utf-8") for path in files}


@pytest.fixture(scope="module")
def raw() -> str:
    assert SOURCE.exists(), f"the execution agent source is missing: {SOURCE}"
    return SOURCE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def code(raw: str) -> str:
    return strip_comments_and_strings(raw)


@pytest.fixture(scope="module")
def keep(raw: str) -> str:
    """The agent's code with its string literals kept (comments gone): where the wire's words and the refusal codes are checked."""
    return strip_comments_and_strings(raw, keep_strings=True)


class TestTheOrderPathIsBarred:
    def test_there_is_exactly_one_order_send_in_the_whole_folder_and_it_is_in_execute_order(self, code: str) -> None:
        sending = r"\b(?:OrderSend(?:Async)?|CTrade|PositionClose\w*|PositionModify|OrderDelete|OrderModify)\b"
        found = {
            name: re.findall(sending, strip_comments_and_strings(text))
            for name, text in sources().items()
            if re.search(sending, strip_comments_and_strings(text))
        }
        assert found == {"TradingOsAgent.mq5": ["OrderSend"]}, found
        assert len(re.findall(r"\bOrderSend\s*\(", code)) == 1
        assert re.search(r"\bOrderSend\s*\(", body_of(code, "ExecuteOrder"))
        for name, text in sources().items():
            assert not re.search(r"#include\s*<\s*Trade", text), f"{name} includes the standard trading library"

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

    def test_the_request_check_script_can_only_ask_the_server_never_send_and_runs_on_a_demo_only(self) -> None:
        script = strip_comments_and_strings(CHECK_SCRIPT.read_text(encoding="utf-8"))
        assert re.search(r"\bOrderCheck\s*\(", script)
        assert not re.search(
            r"\bOrderSend|\bTRADE_ACTION_\w+\s*;", script
        )  # it builds through BuildTradeRequest, sends nothing
        assert re.search(r"ACCOUNT_TRADE_MODE\s*\)\s*!=\s*ACCOUNT_TRADE_MODE_DEMO", script)


class TestEveryKindOfCommandGoesThroughOneChain:
    def test_each_handler_only_reads_its_message_and_hands_a_command_to_the_common_chain(self, code: str) -> None:
        for handler, _ in KINDS.values():
            body = body_of(code, handler)
            assert re.search(r"\bProcessCommand\s*\(\s*json\s*,\s*cmd\s*\)", body), handler
            for forbidden in (
                "OrderSend",
                "ExecuteOrder",
                "BuildTradeRequest",
                "MqlTradeRequest",
                "SendAck",
                "CommandStoreRecord",
            ):
                assert forbidden not in body, f"{handler} must not call {forbidden}: the common chain does"

    def test_the_agent_dispatches_every_message_type_the_core_can_send_for_an_order(self, keep: str) -> None:
        dispatch = body_of(keep, "HandleMessage")
        for message_type, (handler, _) in KINDS.items():
            assert re.search(
                rf'type\s*==\s*"{re.escape(message_type)}"\s*\)\s*\{{\s*{handler}\s*\(\s*json\s*\)', dispatch
            ), message_type

    def test_the_core_writes_no_order_message_the_agent_does_not_dispatch(self, keep: str) -> None:
        wire = WIRE.read_text(encoding="utf-8")
        written = set(re.findall(r'"type":\s*"(execution\.\w+)"', wire))
        assert written == set(KINDS), (
            written
        )  # a new execution.* message on the core's side needs its handler here first
        dispatch = body_of(keep, "HandleMessage")
        for message_type in written:
            assert f'"{message_type}"' in dispatch

    def test_each_handler_reads_only_fields_the_core_really_writes(self, keep: str) -> None:
        common = {"id", "accountId", "expiresAt", "symbol"}
        for message_type, (handler, writer) in KINDS.items():
            written = wire_keys(writer)
            assert {*common, "type"} <= written, writer
            read = set(re.findall(r'Json\w+\(\s*json\s*,\s*"(\w+)"', body_of(keep, handler)))
            assert read - common <= written, (
                f"{handler} reads {sorted(read - common - written)} which {writer} never writes"
            )
            assert message_type in WIRE.read_text(encoding="utf-8")
        process = body_of(keep, "ProcessCommand")
        assert set(re.findall(r'Json\w+\(\s*json\s*,\s*"(\w+)"', process)) <= common

    def test_the_chain_answers_a_replay_first_then_halt_identity_account_and_expiry(self, code: str) -> None:
        body = body_of(code, "AdmitCommand")
        assert re.match(
            r"\s*//?.*?\s*CommandRecord\s+prior\s*;\s*if\s*\(\s*CommandStoreLookup\s*\(", body, re.DOTALL
        ) or re.match(r"\s*CommandRecord\s+prior\s*;\s*if\s*\(\s*CommandStoreLookup\s*\(", body), (
            "the idempotency check must be the first thing a command meets"
        )
        order = [
            body.index(token)
            for token in ("CommandStoreLookup", "IsHalted()", 'g_identity != ""', "g_account_id", "expiresAt")
            if token in body
        ]
        assert order == sorted(order) and len(order) == 5

    def test_the_chain_validates_before_it_acknowledges_and_only_confirm_reaches_execute_order(
        self, code: str, keep: str
    ) -> None:
        body = body_of(code, "ProcessCommand")
        assert (
            body.index("AdmitCommand(")
            < body.index("ValidateTradeCommand(")
            < body.index("SendAck(")
            < body.index("ExecuteOrder(")
        )
        assert len(re.findall(r"\bExecuteOrder\s*\(", code)) == 2  # its definition and this one call
        fork = re.search(r"if\s*\(\s*g_mode\s*==\s*MODE_CONFIRM\s*\)\s*\{(?P<then>.*?)\n   \}", body, re.DOTALL)
        assert fork and "ExecuteOrder(" in fork.group("then")
        words = body_of(keep, "ProcessCommand")
        assert words.rindex('"SIMULATED"') > words.index("ExecuteOrder(")  # every other mode ends in a SIMULATED report

    def test_execute_order_validates_again_builds_checks_writes_unknown_and_only_then_sends(self, keep: str) -> None:
        body = body_of(keep, "ExecuteOrder")
        steps = [
            "g_mode != MODE_CONFIRM",
            "ValidateTradeCommand(",
            "BuildTradeRequest(",
            "OrderCheck(",
            "CommandStoreRecord(inFlight)",
            "OrderSend(",
        ]
        positions = [body.index(step) for step in steps]
        assert positions == sorted(positions), dict(zip(steps, positions, strict=True))
        assert '"UNKNOWN"' in body and "STORE_UNWRITABLE" in body
        assert "return" in body[body.index("CommandStoreRecord(inFlight)") : body.index("OrderSend(")], (
            "an UNKNOWN line that cannot be written must stop the order"
        )

    def test_a_request_is_built_in_one_place_and_no_order_is_sent_without_that_function(self, code: str) -> None:
        assert not re.search(r"\.action\s*=(?!=)", code), "the agent builds no request itself: BuildTradeRequest does"
        assert len(re.findall(r"\bMqlTradeRequest\b", code)) == len(
            re.findall(r"\bMqlTradeRequest\b", body_of(code, "ExecuteOrder"))
        )
        trade_request = strip_comments_and_strings(TRADE_REQUEST.read_text(encoding="utf-8"))
        assert not re.search(r"\bOrder(?:Send|Check)", trade_request)  # building is not sending, nor even checking


class TestWhatEachKindMayDo:
    def test_the_agent_announces_what_it_can_do_and_orders_of_both_types(self, raw: str) -> None:
        hello = raw[raw.index('"\\"capabilities\\":[') :][:200]
        for capability in ("ping", "halt", "dead_man", "limit", "modify", "close", "cancel"):
            assert f'\\"{capability}\\"' in hello, capability
        assert '"\\"orderTypes\\":[\\"market\\",\\"limit\\"],"' in raw

    def test_the_capabilities_the_core_asks_for_are_the_ones_the_agent_announces(self, raw: str) -> None:
        from trading_os.domain.execution.validation import CAPABILITY_BY_KIND, LIMIT_CAPABILITY

        needed = {*CAPABILITY_BY_KIND.values(), LIMIT_CAPABILITY}
        hello = raw[raw.index('"\\"capabilities\\":[') :][:200]
        assert all(f'\\"{capability}\\"' in hello for capability in needed), needed

    def test_a_market_order_and_a_resting_order_are_the_only_ways_to_open(self, keep: str) -> None:
        body = body_of(keep, "ValidateOpenCommand")
        assert 'cmd.orderType != "MARKET" && cmd.orderType != "LIMIT"' in body
        assert (
            body.index("ORDER_TYPE_UNSUPPORTED")
            < body.index("VOLUME_LIMIT")
            < body.index("STOP_MISSING")
            < body.index("POSITIONS_LIMIT")
        )
        assert body.index("POSITIONS_LIMIT") < body.index("SPREAD_LIMIT_MISSING") < body.index("SPREAD_TOO_WIDE")
        assert "PositionsTotal() + OrdersTotal()" in body  # a resting order is a position that has not filled yet

    def test_a_pending_order_never_lives_without_an_end(self, code: str, keep: str) -> None:
        request = strip_comments_and_strings(TRADE_REQUEST.read_text(encoding="utf-8"), keep_strings=True)
        build = body_of(request, "BuildTradeRequest")
        assert re.search(
            r"TRADE_ACTION_PENDING.*?ORDER_TIME_SPECIFIED.*?request\.expiration\s*=\s*pendingExpiration",
            build,
            re.DOTALL,
        )
        assert "ORDER_TIME_GTC" not in request
        assert re.search(
            r"return\s*\(\s*InpPendingMaxMinutes\s*>=\s*1\s*&&\s*InpPendingMaxMinutes\s*<=\s*1440\s*\)\s*\?\s*InpPendingMaxMinutes\s*:\s*60\s*;",
            body_of(code, "PendingMaxMinutes"),
        )
        assert "SYMBOL_EXPIRATION_SPECIFIED" in body_of(
            keep, "ValidateOpenCommand"
        )  # a symbol that cannot expire an order refuses it
        assert "PendingExpiration()" in body_of(code, "ExecuteOrder")

    def test_a_stop_only_ever_tightens_and_is_never_removed(self, keep: str) -> None:
        body = body_of(keep, "ValidateModifyCommand")
        assert re.search(r"cmd\.hasSl\s*&&\s*cmd\.sl\s*<=\s*0\s*\)\s*\{\s*return\s+\"STOP_MISSING", body)
        looser = re.search(
            r"looser\s*=\s*\(current\s*>\s*0\)\s*&&\s*\(isBuy\s*\?\s*\(cmd\.sl\s*<\s*current[^)]*\)\s*:\s*\(cmd\.sl\s*>\s*current",
            body,
        )
        assert looser, "a buy's stop may not go below the current one, a sell's may not go above it"
        assert "STOP_LOOSENED" in body[body.index("looser") :]
        assert "!cmd.hasSl && !cmd.hasTp" in body  # a MODIFY that names nothing is refused, not sent

    def test_a_close_leaves_a_position_the_symbol_can_hold_and_a_partial_is_strictly_inside_the_volume(
        self, keep: str
    ) -> None:
        body = body_of(keep, "ValidateCloseCommand")
        assert "cmd.volume >= heldVolume - 1e-9" in body and "VOLUME_INVALID" in body
        assert "SYMBOL_VOLUME_MIN" in body and "TradeVolumeProblem(" in body
        for rule in ("SPREAD_TOO_WIDE", "VOLUME_LIMIT", "POSITIONS_LIMIT"):
            assert rule not in body, f"closing adds no exposure: {rule} must not stop it"

    def test_the_agent_touches_only_what_it_placed(self, keep: str) -> None:
        for validator in ("ValidateModifyCommand", "ValidateCloseCommand", "ValidateCancelCommand"):
            assert "TargetNotOurs(" in body_of(keep, validator), validator
        assert "magic != InpMagicNumber" in body_of(keep, "TargetNotOurs")
        # positions are found by POSITION_IDENTIFIER (the core's id), never by a ticket the core might hold
        request = strip_comments_and_strings(TRADE_REQUEST.read_text(encoding="utf-8"))
        assert "POSITION_IDENTIFIER" in body_of(request, "TradeSelectPosition")
        assert "request.position = ticket" in body_of(request, "BuildTradeRequest")

    def test_opening_and_moving_a_stop_need_a_tradable_login_closing_and_cancelling_a_closable_one(
        self, code: str
    ) -> None:
        for function in ("ExecuteOrder", "ProcessCommand"):
            body = body_of(code, function)
            assert re.search(
                r"(?:TradeCommandReducesRiskOnly\([^)]*\)|reduceOnly)\s*\?\s*g_closable\s*:\s*g_tradable",
                body.replace("(reduceOnly ? g_closable : g_tradable)", "reduceOnly ? g_closable : g_tradable"),
            ), function
        reduces = body_of(
            strip_comments_and_strings(TRADE_REQUEST.read_text(encoding="utf-8"), keep_strings=True),
            "TradeCommandReducesRiskOnly",
        )
        assert all(kind in reduces for kind in ('"CLOSE"', '"PARTIAL_CLOSE"', '"CANCEL"')) and "MODIFY" not in reduces

    def test_every_refusal_code_the_agent_raises_is_documented_in_the_protocol(self, raw: str) -> None:
        raised = set(re.findall(r'"([A-Z][A-Z_]{2,}): ', strip_comments_and_strings(raw, keep_strings=True)))
        raised |= set(
            re.findall(
                r'"([A-Z][A-Z_]{2,}): ',
                strip_comments_and_strings(TRADE_REQUEST.read_text(encoding="utf-8"), keep_strings=True),
            )
        )
        protocol = PROTOCOL.read_text(encoding="utf-8")
        missing = sorted(code for code in raised if f"`{code}`" not in protocol)
        assert not missing, f"codes raised by the agent but absent from context/execution/protocol.md: {missing}"
        assert {"TARGET_NOT_OURS", "STOP_LOOSENED", "LIMIT_PRICE_INVALID", "STOP_INVALID", "VOLUME_INVALID"} <= raised


class TestTheHaltStopsNewRiskNotTheWayOut:
    """ADR 0033 (agent 1.13): the local halt refuses an opening and a stop move, and lets a closing or a cancelling through."""

    def test_the_halt_refuses_what_is_not_an_exit_at_admission_and_again_in_execute_order(self, code: str) -> None:
        assert re.search(r"if\s*\(\s*IsHalted\(\)\s*&&\s*!exitOnly\s*\)", body_of(code, "AdmitCommand"))
        assert re.search(
            r"IsHalted\(\)\s*&&\s*!TradeCommandReducesRiskOnly\(command\.kind\)", body_of(code, "ExecuteOrder")
        )
        assert not re.search(r"if\s*\(\s*IsHalted\(\)\s*\)", code), (
            "no unconditional halt check may remain on a command path"
        )

    def test_the_chain_tells_admission_whether_the_command_is_an_exit(self, code: str) -> None:
        assert re.search(
            r"AdmitCommand\([^;]*TradeCommandReducesRiskOnly\(cmd\.kind\)\)", body_of(code, "ProcessCommand"), re.DOTALL
        )

    def test_an_exit_is_only_a_closing_or_a_cancelling_never_a_stop_move(self, keep: str) -> None:
        reduces = body_of(
            strip_comments_and_strings(TRADE_REQUEST.read_text(encoding="utf-8"), keep_strings=True),
            "TradeCommandReducesRiskOnly",
        )
        assert (
            all(kind in reduces for kind in ('"CLOSE"', '"PARTIAL_CLOSE"', '"CANCEL"'))
            and "MODIFY" not in reduces
            and "OPEN" not in reduces
        )

    def test_nothing_else_is_relaxed_for_an_exit_while_halted(self, code: str) -> None:
        admit = body_of(code, "AdmitCommand")
        assert (
            re.search(r"if\s*\(\s*g_identity\s*!=\s*\"\"\s*\)", admit)
            and "exitOnly" not in admit[admit.index("g_identity") :]
        )
        assert (
            body_of(code, "ValidateTradeCommand").lstrip().startswith("string dead = DeadManReason()")
        )  # the dead-man still comes first
        assert "g_closable" in body_of(code, "ExecuteOrder")  # an exit still needs a closable login


class TestWhatIsKeptWhenTheOutcomeIsNotKnown:
    def test_the_report_of_a_command_with_no_side_says_null_never_an_empty_string(self, raw: str) -> None:
        body = body_of(strip_comments_and_strings(raw, keep_strings=True), "SendReportRecord")
        assert re.search(r'rec\.side\s*==\s*""\s*\?\s*"\\"side\\":null,"', body)

    def test_a_replay_of_an_unsettled_command_gets_no_report_and_is_never_sent_again(self, code: str) -> None:
        body = body_of(code, "AdmitCommand")
        replay = body[: body.index("return false")]
        assert "CommandStoreIsFinalStatus(prior.status)" in replay and "SendReportRecord" in replay
        assert "ExecuteOrder" not in replay and "OrderSend" not in replay

    def test_the_store_carries_what_an_unknown_line_was_about_and_still_reads_the_old_lines(self) -> None:
        text = strip_comments_and_strings(COMMAND_STORE.read_text(encoding="utf-8"), keep_strings=True)
        parse = body_of(text, "CommandStoreParseLine")
        assert "parts[11]" in parse and "parts[12]" in parse and "parts[13]" in parse
        assert all(f"n >= {count}" in parse for count in (12, 13, 14)), "a line written before 1.12 must still be read"
        write = body_of(text, "CommandStoreRecord")
        assert (
            write.index("rec.retcode") < write.index("rec.kind") < write.index("rec.sl") < write.index("rec.tp")
        )  # appended, not inserted
        for status in ("SUBMITTED", "MODIFIED", "CLOSED", "CANCELLED"):
            assert f'"{status}"' in body_of(text, "CommandStoreIsFinalStatus")

    def test_an_unknown_command_is_resolved_by_looking_never_by_sending(self, code: str) -> None:
        for function in (
            "ResolveUnknownCommand",
            "ReconcileUnknownCommands",
            "SearchActiveOrderForCommand",
            "SearchPositionForModify",
            "SearchHistoryForClose",
            "SearchHistoryForCancel",
            "SearchHistoryForCommand",
        ):
            body = body_of(code, function)
            for sending in ("ExecuteOrder", "OrderSend", "BuildTradeRequest", "ProcessCommand"):
                assert sending not in body, f"{function} must only look at the terminal: it calls {sending}"

    def test_a_modify_that_cannot_be_seen_is_not_found_never_refused_by_deduction(self, keep: str) -> None:
        body = body_of(keep, "SearchPositionForModify")
        assert '"rejected"' not in body
        cancel = body_of(keep, "SearchHistoryForCancel")
        assert (
            cancel.count('"rejected"') == 1 and "ORDER_STATE_FILLED" in cancel
        )  # the one definite negative: it had already filled


class TestTheDeadManSwitch:
    def test_a_command_is_validated_against_the_core_liveness_before_anything_else(self, code: str) -> None:
        body = body_of(code, "ValidateTradeCommand")
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
