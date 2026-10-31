"""JournalService against a real database: the captures that write themselves from the position events, the trades with their R
and the rules they broke, and the file of one trade from the intention to the outcome."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest

from tests.support.builders import make_decision, make_intent, make_request
from tests.support.harness import Harness
from tests.unit.services.test_accounts_service import exness, service
from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.domain.events import PositionClosed, PositionOpened
from trading_os.domain.execution.commands import CommandState, ExecutionCommand
from trading_os.domain.execution.idempotency import request_fingerprint
from trading_os.domain.journal.models import ViolationType
from trading_os.domain.positions.models import ClosedTrade
from trading_os.domain.primitives import Side
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.fake import DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_TYPE_BUY, DEAL_TYPE_SELL, FakeMt5
from trading_os.services.accounts import AccountService
from trading_os.services.journal import JournalService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.shared.errors import NotFound, Unavailable

pytestmark = pytest.mark.db


@dataclass
class Env:
    h: Harness
    accounts: AccountService
    market: MarketDataService
    positions: PositionService
    journal: JournalService
    terminal: FakeMt5
    account_id: str


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def make(h: Harness) -> Env:
    accounts = service(h)
    account = await accounts.create(exness())
    await accounts.connect(account.id)
    market = MarketDataService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock)
    await market.require_spec(account.id, "EURUSDm")  # the broker's specification is all the size check needs
    positions = PositionService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock, market=market)
    journal = JournalService(
        repos=h.repos, events=h.events, clock=h.clock, accounts=accounts, positions=positions, market=market
    )
    journal.subscribe()
    await positions.poll(account.id)  # the baseline, and the balance snapshot the size check reads
    return Env(h, accounts, market, positions, journal, h.terminal(account), account.id)


def server_now(h: Harness) -> int:
    return int(h.clock.now().timestamp())


async def trade_it(
    env: Env, position: int, *, volume: float = 0.05, entry: float = 1.1000, stop: float = 1.0990, exit_: float = 1.1020
) -> None:
    """Open a position at the simulated broker, let the core see it, close it, let the core see that too."""
    h, terminal = env.h, env.terminal
    t0 = server_now(h)
    terminal.add_position(identifier=position, symbol="EURUSDm", side=0, volume=volume, price_open=entry, sl=stop,
                          tp=entry + 0.003, opened_server_time=t0)  # fmt: skip
    terminal.add_deal(position_id=position, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, volume=volume,
                      price=entry, server_time=t0)  # fmt: skip
    h.clock.advance(seconds=2)
    await env.positions.poll(env.account_id)
    terminal.remove_position(position)
    terminal.add_deal(position_id=position, symbol="EURUSDm", side=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, volume=volume,
                      price=exit_, server_time=server_now(h) + 1, profit=(exit_ - entry) * volume * 100_000)  # fmt: skip
    h.clock.advance(seconds=4)
    await env.positions.poll(env.account_id)


# ------------------------------------------------------------------------------------------------------ captures (T05)


async def test_a_position_opened_and_closed_writes_its_two_captures_by_itself(h: Harness) -> None:
    env = await make(h)
    opened_at = h.clock.now()  # the broker's own open time, not the moment the poll noticed it
    await trade_it(env, 801)
    entry, exit_ = await env.journal.captures(env.account_id, "801")
    assert entry is not None and exit_ is not None
    assert (entry.kind, entry.symbol) == ("entry", "EURUSDm")
    assert (entry.entry_price, entry.stop_loss, entry.take_profit, entry.exit_price) == (1.1, 1.099, 1.103, None)
    assert entry.captured_at == opened_at
    assert exit_.kind == "exit" and exit_.exit_price == pytest.approx(1.102) and exit_.captured_at > entry.captured_at
    assert (exit_.entry_price, exit_.stop_loss, exit_.take_profit) == (1.1, 1.099, 1.103)  # one row tells the story
    # Numbers only: nothing of a chart is recorded (ADR 0018).
    assert not {"timeframe", "window_start_utc", "window_end_utc"} & set(type(entry).model_fields)


async def test_captures_are_immutable_and_an_exit_is_never_invented(h: Harness) -> None:
    env = await make(h)
    await trade_it(env, 802)
    before = await env.journal.captures(env.account_id, "802")
    opened = h.recorder.of(PositionOpened)[-1]
    await h.events.publish(
        opened.model_copy(update={"entry_price": 9.9, "stop_loss": 9.0})
    )  # a replayed, altered event
    assert await env.journal.captures(env.account_id, "802") == before

    stranger = ClosedTrade(account_id=env.account_id, broker_position_id="never-opened", symbol="EURUSDm", side=Side.BUY,
                           volume=0.01, realized_pnl=1.0, exit_price=1.1, closed_at=h.clock.now())  # fmt: skip
    await h.events.publish(PositionClosed(account_id=env.account_id, trade=stranger))
    assert await env.journal.captures(env.account_id, "never-opened") == (None, None)  # no entry, no open seen: nothing


async def test_a_trade_opened_and_closed_between_two_polls_is_captured_without_a_stop(h: Harness) -> None:
    env = await make(h)
    t0 = server_now(h) + 1
    env.terminal.add_deal(position_id=4242, symbol="EURUSDm", side=DEAL_TYPE_SELL, entry=DEAL_ENTRY_IN, volume=0.03,
                          price=1.1, server_time=t0)  # fmt: skip
    env.terminal.add_deal(position_id=4242, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_OUT, volume=0.03,
                          price=1.1012, server_time=t0 + 3, profit=-3.6)  # fmt: skip
    h.clock.advance(seconds=10)
    await env.positions.poll(env.account_id)
    entry, exit_ = await env.journal.captures(env.account_id, "4242")
    assert entry is not None and entry.stop_loss == 0.0 and entry.take_profit == 0.0  # MT5's « none », not a guess
    assert exit_ is not None and exit_.exit_price == pytest.approx(1.1012)
    [trade] = await env.journal.trades(env.account_id, h.clock.now() - timedelta(days=1), h.clock.now())
    assert trade.r_multiple is None  # no recorded stop, no R


async def test_a_database_hiccup_while_capturing_never_breaks_the_event_flow(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = await make(h)

    async def broken(*args: object, **kwargs: object) -> None:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(h.repos.positions, "record_capture_entry", broken)
    monkeypatch.setattr(h.repos.positions, "record_capture_exit", broken)
    await trade_it(env, 803)  # nothing raises; the fact is simply not captured
    assert await env.journal.captures(env.account_id, "803") == (None, None)
    assert h.events.handler_errors == 0  # handled and logged, not left for the dispatcher to swallow


# ------------------------------------------------------------------------------------------------------ trades and compliance


async def test_the_journal_lists_trades_with_their_r_multiple_newest_first(h: Harness) -> None:
    env = await make(h)
    await trade_it(env, 811, exit_=1.1020)  # +2R: entry 1.1000, stop 1.0990
    await trade_it(env, 812, exit_=1.0990)  # −1R
    trades = await env.journal.trades(env.account_id, h.clock.now() - timedelta(days=1), h.clock.now())
    assert [t.broker_position_id for t in trades] == ["812", "811"]
    assert [t.r_multiple for t in trades] == [-1.0, 2.0]
    assert all(
        t.has_capture and t.violations == [] and t.opened_at is not None for t in trades
    )  # 08:00 New York: in session
    assert {t.session.value for t in trades if t.session} == {
        "new_york_am"
    }  # 12:00 UTC: tagged by the analysis's buckets
    assert trades[1].side is Side.BUY and trades[1].volume == 0.05 and trades[1].stop_loss == 1.099


async def test_the_rules_a_trade_broke_are_named(h: Harness) -> None:
    env = await make(h)
    repo, now = h.repos, h.clock.now()
    # An oversized trade: 5 lots with a 10-pip stop is ~500 at risk on a 10 000 account allowed 1 %.
    await trade_it(env, 821, volume=5.0, exit_=1.0990)
    # A trade out of session: 13:00 New York.
    late = now.replace(hour=17, minute=0) + timedelta(days=1)
    await repo.positions.record_open(env.account_id, "822", late)
    await repo.positions.record_capture_entry(env.account_id, "822", "EURUSDm", late, 1.1, 1.099, 1.103)
    closed = ClosedTrade(account_id=env.account_id, broker_position_id="822", symbol="EURUSDm", side=Side.BUY,
                         volume=0.05, realized_pnl=-5.0, exit_price=1.099, closed_at=late + timedelta(minutes=5))  # fmt: skip
    await repo.positions.record_closed(closed)
    # A trade opened during a lockout.
    inside = now + timedelta(days=2)
    await repo.risk.open_lockout("lock-1", env.account_id, "Kill switch manuel", inside - timedelta(minutes=5), None)
    await repo.positions.record_open(env.account_id, "823", inside)
    await repo.positions.record_capture_entry(env.account_id, "823", "EURUSDm", inside, 1.1, 1.099, 1.103)
    await repo.positions.record_closed(
        closed.model_copy(update={"broker_position_id": "823", "closed_at": inside + timedelta(minutes=3)})
    )

    window = (now - timedelta(days=1), now + timedelta(days=3))
    trades = {t.broker_position_id: t for t in await env.journal.trades(env.account_id, *window)}
    assert [v.type for v in trades["821"].violations] == [ViolationType.SIZE_POLICY]
    assert [v.type for v in trades["822"].violations] == [ViolationType.SESSION_WINDOW]
    assert ViolationType.LOCKOUT_ACTIVE in {v.type for v in trades["823"].violations}

    summary = await env.journal.compliance(env.account_id, *window)
    assert summary.trade_count == 3 and summary.breached_count == 3 and summary.rate == 0.0
    assert summary.by_type[ViolationType.SIZE_POLICY] == 1 and summary.by_type[ViolationType.SESSION_WINDOW] == 1
    assert (await env.journal.lockouts(env.account_id, now + timedelta(days=3)))[0].lockout_id == "lock-1"


async def test_a_clean_empty_window_scores_one(h: Harness) -> None:
    env = await make(h)
    summary = await env.journal.compliance(env.account_id, h.clock.now() - timedelta(days=1), h.clock.now())
    assert (summary.rate, summary.trade_count, summary.breached_count) == (1.0, 0, 0)


async def test_the_journal_reads_with_the_terminal_off_and_only_skips_what_needs_the_broker(h: Harness) -> None:
    env = await make(h)
    await trade_it(env, 831, volume=5.0, exit_=1.0990)  # oversized, but only the broker's specs can say so
    offline = JournalService(
        repos=h.repos, events=h.events, clock=h.clock, accounts=env.accounts,
        positions=PositionService(accounts=env.accounts, repos=h.repos, events=h.events, clock=h.clock, market=env.market),
        market=MarketDataService(accounts=env.accounts, repos=h.repos, events=h.events, clock=h.clock),
    )  # fmt: skip
    [trade] = await offline.trades(env.account_id, h.clock.now() - timedelta(days=1), h.clock.now())
    assert trade.broker_position_id == "831" and trade.r_multiple == -1.0
    assert trade.violations == []  # no balance and no symbol specification: the size is not judged, nothing is guessed


# ------------------------------------------------------------------------------------------------------ the file of one trade


async def commanded(env: Env, position: int) -> tuple[str, str, str]:
    """A position the core itself commanded: intent → approved decision → executed command naming the position."""
    h = env.h
    intent = make_intent(env.account_id)
    await h.repos.strategy.record_intent(intent)
    decision = make_decision(env.account_id).model_copy(update={"intent_id": intent.intent_id})
    await h.repos.risk.record_decision(decision)
    request = make_request(f"cmd-{position}", account_id=env.account_id, risk_decision_id=decision.decision_id)
    command = ExecutionCommand(
        request=request, fingerprint=request_fingerprint(request), state=CommandState.EXECUTED,
        route=ExecutionRoute.AUTOMATIC, mode=AutonomyMode.ARMED, created_at=h.clock.now(),
        expires_at=h.clock.now() + timedelta(seconds=60), filled_volume=0.05, broker_position_id=str(position),
    )  # fmt: skip
    await h.repos.execution.insert(command, h.clock.now())
    return intent.intent_id, decision.decision_id, request.command_id


async def test_the_file_of_a_trade_follows_the_chain_from_the_intention_to_the_outcome(h: Harness) -> None:
    env = await make(h)
    intent_id, decision_id, command_id = await commanded(env, 841)
    await trade_it(env, 841, exit_=1.1020)
    file = await env.journal.trade_file(env.account_id, "841")
    assert file.status == "closed" and not file.manual and file.trade is not None
    assert file.intent is not None and file.intent.intent_id == intent_id
    assert file.decision is not None and file.decision.decision_id == decision_id
    assert file.command is not None and file.command.command_id == command_id
    assert file.entry_capture is not None and file.exit_capture is not None
    assert file.r_multiple == 2.0 and file.violations == []


async def test_a_position_nobody_commanded_says_so_instead_of_inventing_a_chain(h: Harness) -> None:
    env = await make(h)
    await trade_it(env, 842)
    file = await env.journal.trade_file(env.account_id, "842")
    assert file.manual and file.command is None and file.decision is None and file.intent is None
    assert file.trade is not None and file.entry_capture is not None


async def test_a_position_still_open_has_a_file_without_an_outcome(h: Harness) -> None:
    env = await make(h)
    t0 = server_now(h)
    env.terminal.add_position(identifier=843, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099,
                              tp=1.103, opened_server_time=t0)  # fmt: skip
    env.terminal.add_deal(position_id=843, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, volume=0.05,
                          price=1.1, server_time=t0)  # fmt: skip
    h.clock.advance(seconds=2)
    await env.positions.poll(env.account_id)
    file = await env.journal.trade_file(env.account_id, "843")
    assert file.status == "open" and file.trade is None and file.entry_capture is not None and file.exit_capture is None
    assert file.r_multiple is None and file.violations == []


async def test_a_position_the_core_never_heard_of_is_not_found(h: Harness) -> None:
    env = await make(h)
    with pytest.raises(NotFound) as caught:
        await env.journal.trade_file(env.account_id, "no-such-position")
    assert caught.value.code == "position_not_found"
