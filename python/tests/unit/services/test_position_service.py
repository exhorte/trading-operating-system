"""PositionService against a simulated terminal and a real database: the lifecycle facts of positions, persisted as they
happen — including the ones that open and close between two polls."""

from __future__ import annotations

import pytest

from tests.support.harness import Harness
from tests.unit.services.test_accounts_service import exness, service
from trading_os.domain.accounts.models import AccountSnapshot
from trading_os.domain.events import (
    AccountSnapshotUpdated,
    PositionClosed,
    PositionModified,
    PositionOpened,
    PositionsSnapshotUpdated,
)
from trading_os.domain.positions.models import Position
from trading_os.domain.primitives import Side
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.mt5.fake import DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_TYPE_BUY, DEAL_TYPE_SELL, FakeMt5
from trading_os.services.accounts import AccountService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService

pytestmark = pytest.mark.db


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


async def setup(h: Harness) -> tuple[AccountService, PositionService, FakeMt5, str]:
    accounts = service(h)
    account = await accounts.create(exness())
    await accounts.connect(account.id)
    market = MarketDataService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock)
    positions = PositionService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock, market=market)
    terminal = h.terminal(account)
    return accounts, positions, terminal, account.id


def server_now(h: Harness) -> int:
    return int(h.clock.now().timestamp())


async def test_each_poll_publishes_the_account_and_its_positions(h: Harness) -> None:
    _, positions, terminal, account_id = await setup(h)
    terminal.add_position(identifier=501, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, sl=1.099, tp=1.103)
    assert await positions.poll(account_id) is True
    snapshot = positions.snapshot(account_id)
    assert snapshot is not None and snapshot.balance == 10_000 and snapshot.account_id == account_id
    assert [p.position_id for p in positions.positions(account_id)] == ["501"]
    assert len(h.recorder.of(AccountSnapshotUpdated)) == 1 and len(h.recorder.of(PositionsSnapshotUpdated)) == 1
    assert await positions.guard(account_id) == "1 open position(s)"
    assert positions.total_open_count() == 1 and positions.open_count(account_id) == 1


async def test_a_position_already_open_when_we_attach_is_recorded_once(h: Harness) -> None:
    accounts, positions, terminal, account_id = await setup(h)
    opened = server_now(h) - 3600
    terminal.add_position(
        identifier=501, symbol="EURUSDm", side=1, volume=0.02, price_open=1.1, opened_server_time=opened
    )
    await positions.poll(account_id)
    await positions.poll(account_id)
    events = h.recorder.of(PositionOpened)
    assert len(events) == 1 and events[0].side is Side.SELL and events[0].reconstructed is False
    assert events[0].opened_at.timestamp() == opened  # the real open time, not the moment we noticed it
    # a restarted core finds it already known
    fresh = PositionService(
        accounts=accounts, repos=h.repos, events=h.events, clock=h.clock,
        market=MarketDataService(accounts=accounts, repos=h.repos, events=h.events, clock=h.clock),
    )  # fmt: skip
    h.recorder.clear()
    await fresh.poll(account_id)
    assert h.recorder.of(PositionOpened) == []


async def test_a_new_position_a_modified_stop_and_a_close_with_its_net_result(h: Harness) -> None:
    _, positions, terminal, account_id = await setup(h)
    await positions.poll(account_id)  # baseline: nothing open
    h.recorder.clear()

    t0 = server_now(h)
    terminal.add_position(identifier=777, symbol="EURUSDm", side=0, volume=0.10, price_open=1.1000, sl=1.0990, tp=1.1030,
                          opened_server_time=t0)  # fmt: skip
    terminal.add_deal(position_id=777, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, volume=0.10,
                      price=1.1000, server_time=t0, commission=-0.7)  # fmt: skip
    h.clock.advance(seconds=2)
    await positions.poll(account_id)
    assert [(e.position_id, e.side, e.volume) for e in h.recorder.of(PositionOpened)] == [("777", Side.BUY, 0.10)]

    terminal.positions[0] = terminal.positions[0]._replace(sl=1.0995)
    h.clock.advance(seconds=2)
    await positions.poll(account_id)
    modified = h.recorder.of(PositionModified)
    assert [(m.field, m.previous, m.current) for m in modified] == [("stop_loss", 1.0990, 1.0995)]

    terminal.remove_position(777)
    t1 = server_now(h) + 4
    terminal.add_deal(position_id=777, symbol="EURUSDm", side=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, volume=0.04,
                      price=1.1020, server_time=t1, profit=8.0, commission=-0.3)  # fmt: skip
    terminal.add_deal(position_id=777, symbol="EURUSDm", side=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, volume=0.06,
                      price=1.1030, server_time=t1 + 1, profit=18.0, commission=-0.4, swap=-0.1)  # fmt: skip
    h.clock.advance(seconds=6)
    await positions.poll(account_id)
    closed = h.recorder.of(PositionClosed)
    assert len(closed) == 1
    trade = closed[0].trade
    assert trade.broker_position_id == "777" and trade.side is Side.BUY and trade.volume == 0.10
    assert trade.realized_pnl == pytest.approx(8.0 + 18.0 - 0.7 - 0.3 - 0.4 - 0.1)  # every deal, costs included
    assert trade.exit_price == pytest.approx((1.1020 * 0.04 + 1.1030 * 0.06) / 0.10, abs=1e-5)  # volume-weighted
    assert (await h.repos.positions.closed_between(account_id, h.clock.now().replace(year=2020), h.clock.now()))[
        0
    ] == trade

    await positions.poll(account_id)
    assert len(h.recorder.of(PositionClosed)) == 1  # not twice
    assert await positions.guard(account_id) is None


async def test_a_close_whose_deals_have_not_arrived_yet_is_retried(h: Harness) -> None:
    _, positions, terminal, account_id = await setup(h)
    t0 = server_now(h)
    terminal.add_position(identifier=900, symbol="EURUSDm", side=0, volume=0.05, price_open=1.1, opened_server_time=t0)
    terminal.add_deal(position_id=900, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_IN, volume=0.05,
                      price=1.1, server_time=t0)  # fmt: skip
    await positions.poll(account_id)
    terminal.remove_position(900)  # gone from the list, history not caught up
    h.clock.advance(seconds=2)
    await positions.poll(account_id)
    assert h.recorder.of(PositionClosed) == []
    terminal.add_deal(position_id=900, symbol="EURUSDm", side=DEAL_TYPE_SELL, entry=DEAL_ENTRY_OUT, volume=0.05,
                      price=1.09, server_time=server_now(h), profit=-5.0)  # fmt: skip
    h.clock.advance(seconds=2)
    await positions.poll(account_id)
    assert [c.trade.realized_pnl for c in h.recorder.of(PositionClosed)] == [-5.0]


async def test_a_trade_opened_and_closed_between_two_polls_is_rebuilt_from_history(h: Harness) -> None:
    _, positions, terminal, account_id = await setup(h)
    await positions.poll(account_id)
    h.recorder.clear()
    t0 = server_now(h) + 1
    terminal.add_deal(position_id=4242, symbol="EURUSDm", side=DEAL_TYPE_SELL, entry=DEAL_ENTRY_IN, volume=0.03,
                      price=1.1, server_time=t0)  # fmt: skip
    terminal.add_deal(position_id=4242, symbol="EURUSDm", side=DEAL_TYPE_BUY, entry=DEAL_ENTRY_OUT, volume=0.03,
                      price=1.1012, server_time=t0 + 3, profit=-3.6)  # fmt: skip
    h.clock.advance(seconds=10)
    await positions.poll(account_id)
    opened, closed = h.recorder.of(PositionOpened), h.recorder.of(PositionClosed)
    assert [(o.position_id, o.reconstructed, o.stop_loss) for o in opened] == [("4242", True, 0.0)]
    assert [(c.trade.broker_position_id, c.trade.realized_pnl, c.trade.side) for c in closed] == [
        ("4242", -3.6, Side.SELL)
    ]
    today = await h.repos.risk.today(account_id, h.clock.now())
    assert today.consecutive_losses == 1 and today.last_loss_at is not None  # the streak did not miss it
    await positions.poll(account_id)
    assert len(h.recorder.of(PositionClosed)) == 1


async def test_an_unreadable_terminal_is_counted_and_the_last_snapshot_is_kept(h: Harness) -> None:
    _, positions, terminal, account_id = await setup(h)
    await positions.poll(account_id)
    before = positions.updated_at(account_id)
    terminal.initialized = False  # the terminal stops answering
    h.clock.advance(seconds=2)
    assert await positions.poll(account_id) is False
    failures, error = positions.failures(account_id)
    assert failures == 1 and error is not None
    assert positions.updated_at(account_id) == before and positions.snapshot(account_id) is not None
    terminal.initialized = True
    assert await positions.poll(account_id) is True
    assert positions.failures(account_id) == (0, None)


async def test_an_enricher_can_complete_the_snapshot_and_forgetting_clears_it(h: Harness) -> None:
    _, positions, _, account_id = await setup(h)

    async def enrich(snapshot: AccountSnapshot, open_positions: list[Position]) -> AccountSnapshot:
        return snapshot.model_copy(update={"open_risk_percent": 1.23, "daily_pnl": -42.0})

    positions.set_enricher(enrich)
    await positions.poll(account_id)
    snapshot = positions.snapshot(account_id)
    assert snapshot is not None and snapshot.open_risk_percent == 1.23 and snapshot.daily_pnl == -42.0
    positions.forget(account_id)
    assert positions.snapshot(account_id) is None and positions.positions(account_id) == []
