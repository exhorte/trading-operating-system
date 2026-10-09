"""``weekly-review``: the numbers (pure), the Markdown (pure, compared to the full text) and the command over a real database."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.support.builders import make_account
from trading_os.app.config import Settings
from trading_os.cli.main import main
from trading_os.cli.weekly_review import compute_weekly_stats, render_weekly_review
from trading_os.domain.journal.models import ComplianceSummary, JournalTradeView, Violation, ViolationType
from trading_os.domain.positions.models import ClosedTrade
from trading_os.domain.primitives import Side
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.database.repositories import Repositories

START = datetime(2026, 1, 5, tzinfo=UTC)
END = datetime(2026, 1, 12, tzinfo=UTC)


def trade(
    position: str, symbol: str, pnl: float, *, day: int = 6, side: Side = Side.BUY, capture: bool = False
) -> JournalTradeView:
    return JournalTradeView(
        broker_position_id=position, symbol=symbol, side=side, volume=0.1, entry_price=1.1, exit_price=1.09,
        realized_pnl=pnl, stop_loss=1.08, opened_at=None, closed_at=datetime(2026, 1, day, 10, tzinfo=UTC),
        has_capture=capture,
    )  # fmt: skip


def summary(rate: float, **by_type: int) -> ComplianceSummary:
    counts = {kind: by_type.get(kind.value, 0) for kind in ViolationType}
    return ComplianceSummary(rate=rate, trade_count=0, breached_count=0, by_type=counts, by_trade={})


TRADES = [
    trade("p1", "EURUSDm", -40.0, day=6, capture=True),
    trade("p2", "EURUSDm", 25.5, day=7),
    trade("p3", "XAUUSDm", -12.25, day=8, side=Side.SELL),
    trade("p4", "XAUUSDm", 3.0, day=9),
    trade("p5", "GBPUSDm", -7.0, day=9),
]


# ------------------------------------------------------------------------------------------------------ the numbers


def test_the_week_in_numbers() -> None:
    stats = compute_weekly_stats(START, END, TRADES, summary(0.6, LOCKOUT_ACTIVE=1, SESSION_WINDOW=2))
    assert stats.trade_count == 5 and stats.net_realized_pnl == pytest.approx(-30.75)
    assert [(s.symbol, s.count, s.net_realized_pnl) for s in stats.by_symbol] == [
        ("EURUSDm", 2, pytest.approx(-14.5)), ("XAUUSDm", 2, pytest.approx(-9.25)), ("GBPUSDm", 1, -7.0),
    ]  # fmt: skip
    assert [(v.type, v.count) for v in stats.top_violation_types] == [("SESSION_WINDOW", 2), ("LOCKOUT_ACTIVE", 1)]
    assert [t.broker_position_id for t in stats.worst_trades] == ["p1", "p3", "p5"]  # the three lowest results
    assert stats.compliance_rate == 0.6


def test_an_empty_week_is_all_zeros_and_nothing_is_invented() -> None:
    stats = compute_weekly_stats(START, END, [], summary(1.0))
    assert (stats.trade_count, stats.net_realized_pnl, stats.by_symbol, stats.top_violation_types, stats.worst_trades) == (
        0, 0.0, [], [], []
    )  # fmt: skip


def test_at_most_three_violation_types_are_reported_and_a_type_never_seen_is_not() -> None:
    stats = compute_weekly_stats(START, END, TRADES, summary(0.4, LOCKOUT_ACTIVE=1, SESSION_WINDOW=3, SIZE_POLICY=2))
    assert [v.type for v in stats.top_violation_types] == ["SESSION_WINDOW", "SIZE_POLICY", "LOCKOUT_ACTIVE"]
    assert Violation(type=ViolationType.LOCKOUT_ACTIVE, detail="x").type.value == "LOCKOUT_ACTIVE"


# ------------------------------------------------------------------------------------------------------ the document


def test_the_document_is_rendered_as_the_original_wrote_it() -> None:
    stats = compute_weekly_stats(START, END, TRADES, summary(0.6, LOCKOUT_ACTIVE=1, SESSION_WINDOW=2))
    assert render_weekly_review(stats) == "\n".join(
        [
            "# Weekly review — 2026-01-05 to 2026-01-12",
            "",
            "Facts about the week, not a verdict on the strategy — the KPI is compliance, not P&L (charter.md, principe 2). "
            "Generated automatically, zero manual entry.",
            "",
            "## Statistics",
            "",
            "- Trades closed: **5**",
            "- Net realized P&L: **-$30.75**",
            "- By symbol:",
            "  - EURUSDm: 2 trade(s), -$14.50",
            "  - XAUUSDm: 2 trade(s), -$9.25",
            "  - GBPUSDm: 1 trade(s), -$7.00",
            "",
            "## Compliance",
            "",
            "Weekly compliance rate: **60%**",
            "",
            "Most frequent violations:",
            "",
            "- Trade outside the allowed session: 2 trade(s)",
            "- Trade during an active lockout: 1 trade(s)",
            "",
            "## Worst trades",
            "",
            "- 2026-01-06 · EURUSDm BUY · -$40.00 — [dossier](http://localhost:3000/journal/p1)",
            "- 2026-01-08 · XAUUSDm SELL · -$12.25 — [dossier](http://localhost:3000/journal/p3)",
            "- 2026-01-09 · GBPUSDm BUY · -$7.00 — [dossier](http://localhost:3000/journal/p5)",
            "",
        ]
    )


def test_an_empty_week_says_so() -> None:
    text = render_weekly_review(compute_weekly_stats(START, END, [], summary(1.0)))
    assert "No violations detected this week." in text and "No closed trades this week." in text
    assert "Weekly compliance rate: **100%**" in text and "- By symbol:" not in text


def test_money_and_percent_round_like_the_original() -> None:
    stats = compute_weekly_stats(START, END, [trade("p", "EURUSDm", 0.125)], summary(0.125))
    text = render_weekly_review(stats)
    assert "**+$0.13**" in text  # toFixed rounds the tie up; Python's format would say 0.12
    assert "**13%**" in text  # Math.round(12.5) is 13; round() says 12


# ------------------------------------------------------------------------------------------------------ the command


@pytest.mark.db
def test_the_command_writes_the_document_from_the_journal(
    fresh_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime.now(UTC)

    async def seed() -> None:
        db = Database(fresh_database_url)
        await db.open()
        try:
            repos = Repositories.create(db)
            await repos.accounts.insert(make_account("cli-1"))
            for position, pnl, ago in (("c1", -20.0, 2), ("c2", 35.0, 1)):
                await repos.positions.record_closed(
                    ClosedTrade(
                        account_id="cli-1", broker_position_id=position, symbol="EURUSDm", side=Side.BUY, volume=0.1,
                        realized_pnl=pnl, exit_price=1.1, closed_at=now - timedelta(days=ago),
                    )
                )  # fmt: skip
        finally:
            await db.close()

    asyncio.run(seed(), loop_factory=asyncio.SelectorEventLoop)
    settings = Settings(_env_file=None, database_url=SecretStr(fresh_database_url))
    monkeypatch.setattr("trading_os.app.config.get_settings", lambda: settings)

    assert main(["weekly-review", "--account", "cli-1", "--out-dir", str(tmp_path / "reviews")]) == 0
    written = tmp_path / "reviews" / f"{now:%Y-%m-%d}.md"
    text = written.read_text(encoding="utf-8")
    assert "Trades closed: **2**" in text and "Net realized P&L: **+$15.00**" in text and "EURUSDm: 2 trade(s)" in text
    assert "weekly review computed: 2 trade(s)" in capsys.readouterr().err

    assert main(["weekly-review", "--out-dir", str(tmp_path)]) == 2  # no account named, none configured
    assert "name the account" in capsys.readouterr().err
