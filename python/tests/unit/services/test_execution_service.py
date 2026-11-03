"""The execution engine against a real database: idempotency, the Risk Engine as the only way in, the route each autonomy
mode takes, fail-closed persistence, and the discipline around UNKNOWN."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from tests.support.builders import make_decision, make_request
from tests.support.harness import Harness
from tests.unit.services.test_accounts_service import exness, service
from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.domain.events import (
    ExecutionAcknowledged,
    ExecutionCommandCreated,
    ExecutionCommandSent,
    ExecutionFailed,
    ExecutionRejected,
    ExecutionReported,
    ExecutionUnknown,
)
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.execution.commands import CommandKind, CommandState, ExecutionRequest
from trading_os.domain.execution.reasons import RejectCode
from trading_os.domain.risk.decision import RiskDecision
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.fake import FakeAccount
from trading_os.infrastructure.mt5.wire import ExecutionAck, ExecutionReconciled, ExecutionReport
from trading_os.services.accounts import AccountService
from trading_os.services.execution import ExecutionService
from trading_os.services.market_data import MarketDataService
from trading_os.services.senders import AgentSender, ObserveSender, PaperSender
from trading_os.shared.errors import Conflict, Unavailable

pytestmark = pytest.mark.db

LOGIN = "1000001"


@dataclass
class FakeLink:
    connected: bool = True
    deliver: bool = True
    lines: list[tuple[str, bytes]] = field(default_factory=list)
    halts: list[tuple[str, str]] = field(default_factory=list)
    halted: bool = False
    capabilities: list[str] = field(default_factory=lambda: ["ping", "halt"])
    agent_id: str = "agent-1"  # « mt5-execution-agent-<magic> » when a test needs the agent's magic number

    def status(self, login: str) -> AgentStatus | None:
        if not self.connected:
            return None
        return AgentStatus(
            account_login=login, agent_id=self.agent_id, identity="ok", tradable=True, halted=self.halted,
            capabilities=self.capabilities,
        )  # fmt: skip

    def is_connected(self, login: str | None = None) -> bool:
        return self.connected

    def registered_logins(self) -> list[str]:
        return [LOGIN] if self.connected else []

    async def send_halt(self, login: str, reason: str) -> bool:
        self.halts.append((login, reason))
        return True

    async def send_line(self, login: str, line: bytes) -> bool:
        if not (self.connected and self.deliver):
            return False
        self.lines.append((login, line))
        return True

    def sent(self) -> list[dict[str, object]]:
        return [json.loads(line) for _, line in self.lines]


@dataclass
class Rig:
    h: Harness
    accounts: AccountService
    execution: ExecutionService
    link: FakeLink
    account: Account
    mode: dict[str, AutonomyMode]
    halted: dict[str, bool]

    async def approved(self, **overrides: object) -> RiskDecision:
        decision = make_decision(self.account.id, approved=True).model_copy(update=overrides)
        decision = decision.model_copy(
            update={"expires_at": self.h.clock.now() + timedelta(seconds=60), "decided_at": self.h.clock.now()}
        )
        await self.h.repos.risk.record_decision(decision)
        return decision

    def request(self, command_id: str, decision: RiskDecision | None, **overrides: object) -> ExecutionRequest:
        return make_request(
            command_id,
            account_id=self.account.id,
            risk_decision_id=decision.decision_id if decision else None,
            **overrides,
        )


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def make_rig(h: Harness, mode: AutonomyMode = AutonomyMode.CONFIRM) -> Rig:
    accounts = service(h)
    created = await accounts.create(exness())
    await accounts.connect(created.id)
    market = MarketDataService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock)
    await market.poll_ticks(created.id)
    link = FakeLink()
    holder = {"mode": mode}
    halted = {"on": False}
    ea = AgentSender(link, h.clock)
    execution = ExecutionService(
        accounts=accounts, repos=h.repos, events=h.events, clock=h.clock, link=link,
        senders={
            ExecutionRoute.NONE: ObserveSender(), ExecutionRoute.PAPER: PaperSender(market),
            ExecutionRoute.CONFIRM: ea, ExecutionRoute.AUTOMATIC: ea,
        },
        effective_mode=lambda account: holder["mode"], halted=lambda: halted["on"],
    )  # fmt: skip
    return Rig(h, accounts, execution, link, created, holder, halted)


# ------------------------------------------------------------------------------------------------------ routes


async def test_observe_records_the_command_and_sends_nothing_anywhere(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.OBSERVE)
    decision = await rig.approved()
    outcome = await rig.execution.submit(rig.request("cmd-obs-1", decision), automatic=True)
    assert outcome.command.state is CommandState.SIMULATED and outcome.command.route is ExecutionRoute.NONE
    assert "nothing was sent" in outcome.command.detail
    assert rig.link.lines == []  # the agent socket was never touched
    history = await h.repos.execution.transitions("cmd-obs-1")
    assert [(r["from_state"], r["to_state"]) for r in history] == [(None, "PENDING"), ("PENDING", "SIMULATED")]
    assert h.recorder.of(ExecutionCommandCreated) and h.recorder.of(ExecutionReported)[0].outcome == "simulated"


async def test_paper_fills_at_the_live_quote_in_process(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.PAPER)
    decision = await rig.approved()
    outcome = await rig.execution.submit(rig.request("cmd-paper-1", decision), automatic=True)
    command = outcome.command
    assert command.state is CommandState.SIMULATED and command.route is ExecutionRoute.PAPER
    assert command.filled_volume == 0.05 and command.average_price is not None and command.average_price > 1.0
    assert rig.link.lines == []


async def test_confirm_mode_holds_a_strategy_command_until_a_human_confirms(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.CONFIRM)
    decision = await rig.approved()
    waiting = await rig.execution.submit(rig.request("cmd-conf-1", decision), automatic=True)
    assert waiting.awaiting_confirmation and waiting.command.state is CommandState.PENDING
    assert rig.link.lines == []

    sent = await rig.execution.confirm("cmd-conf-1")
    assert sent.command.state is CommandState.SENT and len(rig.link.lines) == 1
    assert h.recorder.of(ExecutionCommandSent)[0].command_id == "cmd-conf-1"
    again = await rig.execution.confirm("cmd-conf-1")  # a second click is not a second order
    assert again.replayed and len(rig.link.lines) == 1


async def test_a_human_gesture_in_confirm_mode_is_itself_the_confirmation(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.CONFIRM)
    decision = await rig.approved()
    outcome = await rig.execution.submit(rig.request("cmd-human-1", decision))
    assert outcome.command.state is CommandState.SENT and not outcome.awaiting_confirmation
    wire = rig.link.sent()[0]
    assert wire["type"] == "execution.order" and wire["accountId"] == LOGIN and wire["id"] == "cmd-human-1"
    assert wire["symbol"] == "EURUSDm" and wire["side"] == "BUY" and wire["volume"] == 0.05
    assert wire["sl"] == 1.099 and wire["tp"] == 1.103 and wire["orderType"] == "MARKET"


async def test_an_unconfirmed_command_expires_and_cannot_be_confirmed_late(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.CONFIRM)
    decision = await rig.approved()
    await rig.execution.submit(rig.request("cmd-late-1", decision), automatic=True)
    h.clock.advance(seconds=61)
    outcome = await rig.execution.confirm("cmd-late-1")
    assert outcome.command.state is CommandState.EXPIRED
    assert RejectCode.COMMAND_EXPIRED in {r.code for r in outcome.rejections}
    assert rig.link.lines == []


async def test_a_command_can_be_cancelled_only_before_it_is_sent(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.CONFIRM)
    decision = await rig.approved()
    await rig.execution.submit(rig.request("cmd-can-1", decision), automatic=True)
    assert (await rig.execution.cancel("cmd-can-1")).state is CommandState.CANCELLED
    decision2 = await rig.approved()
    await rig.execution.submit(rig.request("cmd-can-2", decision2))
    with pytest.raises(Conflict) as caught:
        await rig.execution.cancel("cmd-can-2")
    assert caught.value.code == "not_cancellable"


# ------------------------------------------------------------------------------------------------------ idempotency


async def test_the_same_command_id_never_sends_twice(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    decision = await rig.approved()
    request = rig.request("cmd-idem-1", decision)
    first = await rig.execution.submit(request, automatic=True)
    second = await rig.execution.submit(request, automatic=True)
    assert first.command.state is CommandState.SENT and second.replayed and second.command.command_id == "cmd-idem-1"
    assert len(rig.link.lines) == 1
    assert await h.db.fetch_value("SELECT count(*) FROM execution_commands") == 1

    with pytest.raises(Conflict) as caught:
        await rig.execution.submit(request.model_copy(update={"volume": 0.01}), automatic=True)
    assert caught.value.code == RejectCode.DUPLICATE_CONFLICT.value and len(rig.link.lines) == 1


# ------------------------------------------------------------------------------------------------------ validation


async def rejected_codes(
    rig: Rig, command_id: str, decision: RiskDecision | None, **overrides: object
) -> set[RejectCode]:
    outcome = await rig.execution.submit(rig.request(command_id, decision, **overrides), automatic=True)
    assert outcome.command.state is CommandState.REJECTED, outcome.command.state
    stored = await rig.h.repos.execution.get(command_id)
    assert stored is not None and stored.state is CommandState.REJECTED  # the refusal is on record, whole
    assert rig.link.lines == []
    return {r.code for r in outcome.rejections}


async def test_no_order_without_an_approved_decision_that_matches_it(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    assert await rejected_codes(rig, "cmd-rej-1", None) == {RejectCode.RISK_NOT_APPROVED}
    refused = await rig.approved(approved=False, reasons=["news_restriction"])
    assert RejectCode.RISK_NOT_APPROVED in await rejected_codes(rig, "cmd-rej-2", refused)
    approved = await rig.approved()
    assert RejectCode.RISK_DECISION_MISMATCH in await rejected_codes(rig, "cmd-rej-3", approved, volume=0.5)
    assert RejectCode.RISK_DECISION_MISMATCH in await rejected_codes(rig, "cmd-rej-4", approved, stop_loss=1.090)
    assert RejectCode.SYMBOL_MISMATCH in await rejected_codes(rig, "cmd-rej-5", approved, symbol="GBPUSDm")
    h.clock.advance(seconds=120)
    assert RejectCode.RISK_DECISION_EXPIRED in await rejected_codes(rig, "cmd-rej-6", approved)
    for event in h.recorder.of(ExecutionRejected):
        assert event.code and event.detail


async def test_a_stop_loss_is_mandatory_and_a_limit_order_needs_an_agent_that_announces_it(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    decision = await rig.approved()
    assert RejectCode.STOP_REQUIRED in await rejected_codes(rig, "cmd-stop-1", decision, stop_loss=None)
    # ADR 0023: a limit order is carried, but only to an agent that says it can place one (agent 1.11 says nothing)
    assert RejectCode.AGENT_CAPABILITY_MISSING in await rejected_codes(
        rig, "cmd-stop-2", decision, order_type="limit", price=1.0995
    )
    assert RejectCode.ORDER_TYPE_UNSUPPORTED in await rejected_codes(
        rig, "cmd-stop-3", decision, order_type="stop", price=1.1005
    )


async def test_the_account_must_be_the_one_really_attached(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    decision = await rig.approved()
    other = await rig.accounts.create(exness(login=7_000_007, terminal_path="C:/MT5/other"))
    terminal = h.terminal(rig.account)
    terminal.accounts[7_000_007] = FakeAccount(login=7_000_007, server="Exness-MT5Trial", password="x")
    terminal.current_login = 7_000_007  # the user switched the terminal to another account by hand
    outcome = await rig.execution.submit(rig.request("cmd-acct-1", decision), automatic=True)
    assert outcome.command.state is CommandState.REJECTED
    assert RejectCode.ACCOUNT_MISMATCH in {r.code for r in outcome.rejections}
    assert other.id in outcome.command.detail  # the message says which account the terminal is really on
    assert rig.link.lines == []


async def test_unknown_and_disconnected_accounts_are_refused(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    decision = await rig.approved()
    ghost = make_request("cmd-ghost-1", account_id="no-such-account", risk_decision_id=decision.decision_id)
    outcome = await rig.execution.submit(ghost, automatic=True)
    assert outcome.command.state is CommandState.REJECTED and RejectCode.ACCOUNT_NOT_CONNECTED in {
        r.code for r in outcome.rejections
    }
    await rig.accounts.disconnect(rig.account.id)
    assert RejectCode.ACCOUNT_NOT_CONNECTED in await rejected_codes(rig, "cmd-ghost-2", decision)


async def test_trading_switch_halt_and_missing_agent_are_refused(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    decision = await rig.approved()
    await rig.accounts.set_trading_enabled(rig.account.id, False)
    assert RejectCode.TRADING_DISABLED in await rejected_codes(rig, "cmd-gate-1", decision)
    await rig.accounts.set_trading_enabled(rig.account.id, True)

    rig.halted["on"] = True
    assert RejectCode.HALTED in await rejected_codes(rig, "cmd-gate-2", decision)
    rig.halted["on"] = False
    rig.link.halted = True  # the agent's own local kill switch
    assert RejectCode.HALTED in await rejected_codes(rig, "cmd-gate-3", decision)
    rig.link.halted = False

    rig.link.connected = False
    assert RejectCode.AGENT_UNREACHABLE in await rejected_codes(rig, "cmd-gate-4", decision)


async def test_a_halted_system_still_sends_a_human_closing_and_cancelling_and_nothing_else(h: Harness) -> None:
    """ADR 0033: HALTED stops new risk, not the way out. By hand a close and a cancel reach the agent; an opening, a stop move and every
    automatic command are refused, as before."""
    rig = await make_rig(h, AutonomyMode.ARMED)
    rig.mode["mode"] = AutonomyMode.HALTED
    rig.halted["on"] = True
    rig.link.capabilities = ["ping", "halt", "modify", "close", "cancel"]
    decision = await rig.approved()

    close = await rig.execution.submit(
        make_request(
            "cmd-halt-close",
            account_id=rig.account.id,
            kind=CommandKind.CLOSE,
            position_id="777",
            risk_decision_id=None,
        )
    )
    assert close.command.state is CommandState.SENT and close.rejections == []
    cancel = await rig.execution.submit(
        make_request(
            "cmd-halt-cancel", account_id=rig.account.id, kind=CommandKind.CANCEL, order_id="55", risk_decision_id=None
        )
    )
    assert cancel.command.state is CommandState.SENT
    assert [json.loads(line)["type"] for _, line in rig.link.lines] == ["execution.close", "execution.cancel"]

    sent_before = len(rig.link.lines)
    refused = [
        await rig.execution.submit(rig.request("cmd-halt-open", decision)),
        await rig.execution.submit(rig.request("cmd-halt-open-auto", decision), automatic=True),
        await rig.execution.submit(
            make_request(
                "cmd-halt-modify",
                account_id=rig.account.id,
                kind=CommandKind.MODIFY,
                position_id="777",
                stop_loss=1.0995,
                risk_decision_id=None,
            )
        ),
        await rig.execution.submit(
            make_request(
                "cmd-halt-close-auto",
                account_id=rig.account.id,
                kind=CommandKind.CLOSE,
                position_id="777",
                risk_decision_id=None,
            ),
            automatic=True,
        ),
    ]
    for outcome in refused:
        assert outcome.command.state is CommandState.REJECTED and RejectCode.HALTED in {
            r.code for r in outcome.rejections
        }
    assert len(rig.link.lines) == sent_before  # none of them left the core


async def test_the_agents_local_halt_does_not_stop_a_human_exit_either(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    rig.link.capabilities = ["ping", "halt", "close", "cancel"]
    rig.link.halted = True  # the agent's own kill switch, set on the chart or by the core
    decision = await rig.approved()
    close = await rig.execution.submit(
        make_request(
            "cmd-lhalt-close",
            account_id=rig.account.id,
            kind=CommandKind.CLOSE,
            position_id="777",
            risk_decision_id=None,
        )
    )
    assert close.command.state is CommandState.SENT and rig.link.sent()[-1]["type"] == "execution.close"
    opening = await rig.execution.submit(rig.request("cmd-lhalt-open", decision), automatic=True)
    assert opening.command.state is CommandState.REJECTED and RejectCode.HALTED in {r.code for r in opening.rejections}
    automatic_close = await rig.execution.submit(
        make_request(
            "cmd-lhalt-close-auto",
            account_id=rig.account.id,
            kind=CommandKind.CLOSE,
            position_id="777",
            risk_decision_id=None,
        ),
        automatic=True,
    )
    assert automatic_close.command.state is CommandState.REJECTED


@pytest.mark.parametrize("mode", [AutonomyMode.OFF, AutonomyMode.OBSERVE, AutonomyMode.PAPER])
async def test_a_human_closing_reaches_the_agent_in_off_observe_and_paper_too(h: Harness, mode: AutonomyMode) -> None:
    """ADR 0034: the way out is never closed by the mode. A closing issued by a human gesture goes to the agent in OFF, OBSERVE and PAPER
    like in CONFIRM and HALTED; without an agent that can close it is refused for that reason — not silently recorded as if it had worked."""
    rig = await make_rig(h, mode)
    rig.link.capabilities = ["ping", "halt", "close", "cancel"]
    outcome = await rig.execution.submit(
        make_request(
            f"cmd-{mode.value}-close", account_id=rig.account.id, kind=CommandKind.CLOSE, position_id="777",
            risk_decision_id=None,
        )
    )  # fmt: skip
    assert outcome.command.route is ExecutionRoute.CONFIRM and outcome.command.state is CommandState.SENT
    assert len(rig.link.lines) == 1

    rig.link.capabilities = ["ping", "halt"]  # an agent that cannot close: refused, with the reason
    refused = await rig.execution.submit(
        make_request(
            f"cmd-{mode.value}-close-2", account_id=rig.account.id, kind=CommandKind.CLOSE, position_id="778",
            risk_decision_id=None,
        )
    )  # fmt: skip
    assert refused.command.state is CommandState.REJECTED
    assert RejectCode.AGENT_CAPABILITY_MISSING in {r.code for r in refused.rejections}


@pytest.mark.parametrize("mode", [AutonomyMode.OFF, AutonomyMode.OBSERVE, AutonomyMode.PAPER])
async def test_an_automatic_closing_still_follows_the_mode_only_the_human_gesture_opens_the_way(
    h: Harness, mode: AutonomyMode
) -> None:
    rig = await make_rig(h, mode)
    rig.link.capabilities = ["ping", "halt", "close", "cancel"]
    outcome = await rig.execution.submit(
        make_request(
            f"cmd-{mode.value}-auto-close", account_id=rig.account.id, kind=CommandKind.CLOSE, position_id="777",
            risk_decision_id=None,
        ),
        automatic=True,
    )  # fmt: skip
    assert rig.link.lines == []
    assert outcome.command.route in {ExecutionRoute.NONE, ExecutionRoute.PAPER}


async def test_the_disable_trading_switch_stops_risk_not_the_way_out(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.CONFIRM)
    rig.link.capabilities = ["ping", "halt", "close", "cancel", "modify"]
    await rig.accounts.set_trading_enabled(rig.account.id, False)
    close = await rig.execution.submit(
        make_request(
            "cmd-dis-close", account_id=rig.account.id, kind=CommandKind.CLOSE, position_id="777", risk_decision_id=None
        )
    )
    assert close.command.state is CommandState.SENT  # a human closing goes through
    modify = await rig.execution.submit(
        make_request(
            "cmd-dis-modify", account_id=rig.account.id, kind=CommandKind.MODIFY, position_id="777", stop_loss=1.09,
            risk_decision_id=None,
        )
    )  # fmt: skip
    assert RejectCode.TRADING_DISABLED in {r.code for r in modify.rejections}  # a stop move is not an exit


async def test_only_the_active_account_receives_automatic_commands(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    second = await rig.accounts.create(exness(login=8_000_008, terminal_path="C:/MT5/second"))
    assert (
        rig.accounts.active_account_id == rig.account.id
    )  # the second one is registered, not connected: it cannot be taken
    decision = make_decision(second.id, approved=True).model_copy(
        update={"expires_at": h.clock.now() + timedelta(seconds=60)}
    )
    await h.repos.risk.record_decision(decision)
    request = make_request("cmd-act-1", account_id=second.id, risk_decision_id=decision.decision_id)
    outcome = await rig.execution.submit(request, automatic=True)
    assert RejectCode.NOT_ACTIVE_ACCOUNT in {r.code for r in outcome.rejections}
    assert outcome.command.state is CommandState.REJECTED


async def test_commands_the_agent_cannot_handle_are_refused_not_sent_into_the_void(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    outcome = await rig.execution.submit(
        make_request("cmd-close-1", account_id=rig.account.id, kind=CommandKind.CLOSE, position_id="777"),
        automatic=True,
    )
    assert RejectCode.AGENT_CAPABILITY_MISSING in {r.code for r in outcome.rejections}
    assert rig.link.lines == []


# ------------------------------------------------------------------------------------------------------ fail closed


async def test_nothing_is_sent_when_the_command_cannot_be_recorded(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    decision = await rig.approved()

    async def broken(command: object, at: object) -> bool:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(h.repos.execution, "insert", broken)
    with pytest.raises(Unavailable) as caught:
        await rig.execution.submit(rig.request("cmd-store-1", decision), automatic=True)
    assert caught.value.code == RejectCode.STORE_UNAVAILABLE.value
    assert rig.link.lines == []


async def test_an_agent_that_cannot_be_reached_at_send_time_leaves_a_failed_unsent_command(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    decision = await rig.approved()
    rig.link.deliver = False  # registered, but the write fails
    outcome = await rig.execution.submit(rig.request("cmd-down-1", decision), automatic=True)
    assert (
        outcome.command.state is CommandState.FAILED
        and outcome.command.reject_code == RejectCode.AGENT_UNREACHABLE.value
    )
    assert "nothing was sent" in outcome.command.detail
    assert h.recorder.of(ExecutionFailed) and not h.recorder.of(ExecutionCommandSent)


# ------------------------------------------------------------------------------------------------------ the agent answers


def report(command_id: str, status: str, **fields: object) -> ExecutionReport:
    return ExecutionReport.model_validate(
        {"account_id": LOGIN, "time": 1_790_000_000_000, "command_id": command_id, "status": status,
         "symbol": "EURUSDm", "side": "BUY", **fields}
    )  # fmt: skip


async def sent_command(rig: Rig, command_id: str) -> None:
    decision = await rig.approved()
    outcome = await rig.execution.submit(rig.request(command_id, decision), automatic=True)
    assert outcome.command.state is CommandState.SENT


async def test_ack_then_fill_walks_the_happy_path(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    await sent_command(rig, "cmd-ok-1")
    await rig.execution.on_ack(LOGIN, ExecutionAck(account_id=LOGIN, command_id="cmd-ok-1", status="ACCEPTED"))
    assert (await rig.execution.get("cmd-ok-1")).state is CommandState.ACKNOWLEDGED  # type: ignore[union-attr]
    await rig.execution.on_report(
        LOGIN, report("cmd-ok-1", "FILLED", filled_volume=0.05, average_price=1.0851, broker_order_id=9001,
                      broker_position_id=9001, broker_retcode="10009", detail="done"),
    )  # fmt: skip
    done = await rig.execution.get("cmd-ok-1")
    assert done is not None and done.state is CommandState.EXECUTED
    assert (done.filled_volume, done.average_price, done.broker_position_id) == (0.05, 1.0851, "9001")
    assert [e.status for e in h.recorder.of(ExecutionAcknowledged)] == ["ACCEPTED"]
    reported = h.recorder.of(ExecutionReported)[-1]
    assert reported.outcome == "executed" and reported.broker_position_id == "9001"
    await rig.execution.on_report(LOGIN, report("cmd-ok-1", "FILLED", filled_volume=0.05))  # a repeated report
    assert (await rig.execution.get("cmd-ok-1")).state is CommandState.EXECUTED  # type: ignore[union-attr]


@pytest.mark.parametrize("status", ["SUBMITTED", "MODIFIED", "CLOSED", "CANCELLED"])
async def test_every_success_report_of_the_agent_takes_the_command_to_executed(h: Harness, status: str) -> None:
    """ADR 0029: a resting LIMIT order, a stop move, a close and a cancel are reported with their own words, and each one means
    « the broker did it » — none of them is ignored and left to time out into UNKNOWN."""
    rig = await make_rig(h, AutonomyMode.ARMED)
    command_id = f"cmd-{status.lower()}-1"
    await sent_command(rig, command_id)
    await rig.execution.on_ack(LOGIN, ExecutionAck(account_id=LOGIN, command_id=command_id, status="ACCEPTED"))
    # a report without a side (a management command has none of its own) is read, not dropped
    await rig.execution.on_report(LOGIN, report(command_id, status, side=None, broker_order_id=9002, detail=status))
    done = await rig.execution.get(command_id)
    assert done is not None and done.state is CommandState.EXECUTED
    assert h.recorder.of(ExecutionReported)[-1].outcome == "executed"


def test_the_wire_reads_the_reports_the_1_12_agent_writes() -> None:
    """The exact shapes TradingOsAgent.mq5 puts on the wire: a null side, ids as strings, the new CANCELLED status."""
    from trading_os.infrastructure.mt5.wire import SUCCESS_REPORT_STATUSES, ExecutionReport, decode_line

    line = (
        '{"version":1,"type":"execution.report","accountId":"1000001","time":1790000000000,"commandId":"cmd-x-1",'
        '"status":"CANCELLED","symbol":"EURUSDm","side":null,"brokerOrderId":"9002","brokerPositionId":null,'
        '"filledVolume":null,"averagePrice":null,"brokerRetcode":"10009","detail":"CANCELLED pending order 9002 EURUSDm"}'
    )
    message = decode_line(line).message
    assert isinstance(message, ExecutionReport) and message.status == "CANCELLED" and message.side is None
    assert message.broker_order_id == "9002" and message.status in SUCCESS_REPORT_STATUSES
    # an empty side — what 1.11 could write for a report without one — would drop the whole frame: that is why 1.12 writes null
    assert decode_line(line.replace('"side":null', '"side":""')).message is None


async def test_a_final_report_that_overtakes_a_lost_ack_still_settles_the_command(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    await sent_command(rig, "cmd-ovr-1")
    await rig.execution.on_report(LOGIN, report("cmd-ovr-1", "FILLED", filled_volume=0.05, average_price=1.1))
    assert (await rig.execution.get("cmd-ovr-1")).state is CommandState.EXECUTED  # type: ignore[union-attr]


async def test_the_agent_refusing_the_order_is_recorded_with_its_code(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    await sent_command(rig, "cmd-ref-1")
    await rig.execution.on_ack(
        LOGIN,
        ExecutionAck(account_id=LOGIN, command_id="cmd-ref-1", status="REJECTED", reason="DEAD_MAN: no ping for 31s"),
    )
    command = await rig.execution.get("cmd-ref-1")
    assert command is not None and command.state is CommandState.REJECTED and command.reject_code == "DEAD_MAN"
    assert h.recorder.of(ExecutionRejected)[-1].code == "DEAD_MAN"


async def test_an_ambiguous_broker_answer_is_unknown_never_failed(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    for index, (retcode, detail) in enumerate(
        [
            ("10012", "request timed out"),
            ("10011", "processing error"),
            ("10031", "no connection"),
            (None, "order_send returned no result"),
        ]
    ):
        command_id = f"cmd-amb-{index}"
        await sent_command(rig, command_id)
        await rig.execution.on_report(LOGIN, report(command_id, "FAILED", broker_retcode=retcode, detail=detail))
        assert (await rig.execution.get(command_id)).state is CommandState.UNKNOWN, retcode  # type: ignore[union-attr]
    assert len(h.recorder.of(ExecutionUnknown)) == 4 and h.recorder.of(ExecutionFailed) == []


async def test_a_definite_refusal_is_a_real_failure(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    await sent_command(rig, "cmd-fail-1")
    await rig.execution.on_report(LOGIN, report("cmd-fail-1", "FAILED", broker_retcode="10019", detail="no money"))
    assert (await rig.execution.get("cmd-fail-1")).state is CommandState.FAILED  # type: ignore[union-attr]
    await sent_command(rig, "cmd-fail-2")
    await rig.execution.on_report(LOGIN, report("cmd-fail-2", "FAILED", detail="journal unwritable — order NOT sent"))
    assert (await rig.execution.get("cmd-fail-2")).state is CommandState.FAILED  # type: ignore[union-attr]


async def test_unknown_only_leaves_through_reconciliation_and_never_replays(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    await sent_command(rig, "cmd-unk-1")
    await rig.execution.on_report(LOGIN, report("cmd-unk-1", "FAILED", broker_retcode="10012", detail="timeout"))
    lines_before = len(rig.link.lines)
    # a late, replayed FILLED report is evidence, not a way back into the happy path
    await rig.execution.on_report(
        LOGIN, report("cmd-unk-1", "FILLED", filled_volume=0.05, average_price=1.1, replayed=True)
    )
    command = await rig.execution.get("cmd-unk-1")
    assert command is not None and command.state is CommandState.RECONCILED and command.filled_volume == 0.05
    assert "late report" in command.detail and len(rig.link.lines) == lines_before
    steps = [r["to_state"] for r in await h.repos.execution.transitions("cmd-unk-1")]
    assert steps == ["PENDING", "SENT", "UNKNOWN", "RECONCILING", "RECONCILED"]


async def test_the_agent_reconciliation_message_resolves_or_keeps_the_doubt(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    await sent_command(rig, "cmd-rec-1")
    await rig.execution.sweep()
    h.clock.advance(seconds=20)
    await rig.execution.sweep()
    assert (await rig.execution.get("cmd-rec-1")).state is CommandState.UNKNOWN  # type: ignore[union-attr]

    nothing = ExecutionReconciled(
        account_id=LOGIN, command_id="cmd-rec-1", outcome="not_found", attempts=1, detail="not in history"
    )
    await rig.execution.on_reconciled(LOGIN, nothing)
    assert (await rig.execution.get("cmd-rec-1")).state is CommandState.RECONCILING  # type: ignore[union-attr]  # stays in doubt
    found = ExecutionReconciled(account_id=LOGIN, command_id="cmd-rec-1", outcome="executed", attempts=2, broker_position_id="9002",
                                filled_volume=0.05, average_price=1.1, detail="deal found")  # fmt: skip
    await rig.execution.on_reconciled(LOGIN, found)
    done = await rig.execution.get("cmd-rec-1")
    assert done is not None and done.state is CommandState.RECONCILED and done.broker_position_id == "9002"
    assert (await h.repos.execution.reconciliations(rig.account.id))[0].outcome == "executed"


# ------------------------------------------------------------------------------------------------------ housekeeping


async def test_silence_after_the_send_becomes_unknown_not_failed(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    await sent_command(rig, "cmd-sil-1")
    assert await rig.execution.sweep() == 0  # not yet
    h.clock.advance(seconds=16)
    assert await rig.execution.sweep() == 1
    command = await rig.execution.get("cmd-sil-1")
    assert command is not None and command.state is CommandState.UNKNOWN and "no acknowledgement" in command.detail

    await sent_command(rig, "cmd-sil-2")
    await rig.execution.on_ack(LOGIN, ExecutionAck(account_id=LOGIN, command_id="cmd-sil-2", status="ACCEPTED"))
    h.clock.advance(seconds=91)
    assert await rig.execution.sweep() == 1
    assert (await rig.execution.get("cmd-sil-2")).state is CommandState.UNKNOWN  # type: ignore[union-attr]


async def test_a_restart_never_replays_what_may_have_reached_the_broker(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.CONFIRM)
    decision = await rig.approved()
    await rig.execution.submit(rig.request("cmd-boot-1", decision), automatic=True)  # PENDING, unconfirmed
    rig.mode["mode"] = AutonomyMode.ARMED
    await sent_command(rig, "cmd-boot-2")  # SENT
    lines = len(rig.link.lines)
    assert await rig.execution.recover() == 2
    assert (await rig.execution.get("cmd-boot-1")).state is CommandState.EXPIRED  # type: ignore[union-attr]
    assert (await rig.execution.get("cmd-boot-2")).state is CommandState.UNKNOWN  # type: ignore[union-attr]
    assert len(rig.link.lines) == lines


async def test_a_command_in_doubt_blocks_disconnecting_the_account(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    rig.accounts.add_guard(rig.execution.guard)
    await sent_command(rig, "cmd-guard-1")
    with pytest.raises(Conflict) as caught:
        await rig.accounts.disconnect(rig.account.id)
    assert "not yet settled" in caught.value.details["reasons"][0]
    await rig.execution.on_report(LOGIN, report("cmd-guard-1", "FILLED", filled_volume=0.05))
    await rig.execution.on_report(LOGIN, report("cmd-guard-1", "FILLED", filled_volume=0.05))
    assert await rig.execution.guard(rig.account.id) is None  # settled: nothing in doubt any more


async def test_halting_reaches_every_connected_agent(h: Harness) -> None:
    rig = await make_rig(h, AutonomyMode.ARMED)
    assert await rig.execution.halt_agents("critical error") == 1
    assert rig.link.halts == [(LOGIN, "critical error")]
    rig.link.connected = False
    assert await rig.execution.halt_agents("again") == 0
