"""Metrics, Monte Carlo, rolling windows, replay and the report (ADR 0026)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.unit.domain.s01.scenario import BULLISH_HTF, CONTEXT, H1_DISCOUNT, REACTION
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Side, Timeframe
from trading_os.domain.strategy.s01.config import S01Config
from trading_os.domain.strategy.s01.proposal import S01_VARIANT
from trading_os.domain.strategy.s02 import S02Config, s02_variant
from trading_os.domain.validation.metrics import MIN_TRADES_FOR_CONCLUSION, breakdown, compute_metrics
from trading_os.domain.validation.montecarlo import MonteCarloSettings, monte_carlo
from trading_os.domain.validation.replay import CandleSet, replay
from trading_os.domain.validation.report import RunSettings, fingerprint, ledger_entry, previous_looks, run_validation
from trading_os.domain.validation.simulate import SimulatedTrade, TradeCosts, TradeSpec
from trading_os.domain.validation.walkforward import WalkForwardSettings, rolling_windows


def trade(closed: datetime, r: float | None, *, window: str = "new_york_am") -> SimulatedTrade:
    spec = TradeSpec(symbol="EURUSDm", side=Side.BUY, entry=1.1, stop=1.099, target=1.103, placed_at=closed)
    if r is None:
        return SimulatedTrade(spec=spec, outcome="unfilled")
    return SimulatedTrade(
        spec=spec, outcome="target" if r > 0 else "stop", filled_at=closed - timedelta(minutes=5), closed_at=closed,
        r_net=r, r_gross=r, minutes_held=5, window=window,
    )  # fmt: skip


class TestMetrics:
    def test_the_arithmetic(self) -> None:
        m = compute_metrics([2.0, -1.0, -1.0, 3.0])
        assert (m.trades, m.wins, m.losses) == (4, 2, 2)
        assert m.expectancy_r == pytest.approx(0.75) and m.total_r == pytest.approx(3.0)
        assert m.profit_factor == pytest.approx(2.5) and m.win_rate == pytest.approx(0.5)
        assert m.max_drawdown_r == pytest.approx(2.0) and m.longest_losing_streak == 2
        assert not m.enough_trades

    def test_nothing_is_invented_from_nothing(self) -> None:
        m = compute_metrics([])
        assert m.trades == 0 and m.win_rate is None and m.expectancy_r is None and m.profit_factor is None

    def test_a_profit_factor_needs_a_loss_under_it(self) -> None:
        assert compute_metrics([1.0, 2.0]).profit_factor is None

    def test_enough_trades_is_a_stated_threshold(self) -> None:
        assert compute_metrics([0.1] * MIN_TRADES_FOR_CONCLUSION).enough_trades

    def test_breakdown_by_window_ignores_what_was_never_filled(self) -> None:
        day = datetime(2026, 11, 2, 15, tzinfo=UTC)
        found = breakdown(
            [trade(day, 1.0), trade(day, -1.0, window="london"), trade(day, None)], lambda t: t.window or "outside"
        )
        assert set(found) == {"new_york_am", "london"} and found["london"].trades == 1


class TestMonteCarlo:
    SETTINGS = MonteCarloSettings(risk_percent=1.0, paths=500, horizon_days=10, seed=7)

    def test_the_same_data_and_seed_give_the_same_answer(self) -> None:
        days = [[1.0, -1.0], [2.0], [-1.0], [-1.0, -1.0, 3.0]]
        assert monte_carlo(days, self.SETTINGS) == monte_carlo(days, self.SETTINGS)
        assert monte_carlo(days, self.SETTINGS) != monte_carlo(days, self.SETTINGS.model_copy(update={"seed": 8}))

    def test_nothing_to_draw_from_is_no_answer(self) -> None:
        assert monte_carlo([], self.SETTINGS) is None and monte_carlo([[], []], self.SETTINGS) is None

    def test_days_that_can_never_reach_a_limit_never_breach_it(self) -> None:
        result = monte_carlo([[1.0], [-1.0]], self.SETTINGS)
        assert result is not None and result.p_daily_breach == 0.0 and result.p_total_breach == 0.0
        assert result.return_p05 <= result.return_p50 <= result.return_p95
        assert result.max_drawdown_p50 <= result.max_drawdown_p95

    def test_a_day_that_loses_the_daily_limit_always_breaches_it(self) -> None:
        result = monte_carlo([[-1.0] * 6], self.SETTINGS)  # six full losses at 1 % = -6 % in a day
        assert result is not None and result.p_daily_breach == 1.0 and result.p_total_breach == 1.0

    def test_the_total_limit_is_an_equity_floor_not_a_single_day(self) -> None:
        result = monte_carlo(
            [[-1.0] * 3], self.SETTINGS
        )  # -3 % a day: never the daily limit, the floor after four days
        assert result is not None and result.p_daily_breach == 0.0 and result.p_total_breach == 1.0


class TestRollingWindows:
    def test_each_window_is_measured_on_its_own(self) -> None:
        start = datetime(2026, 11, 2, tzinfo=UTC)
        trades = [
            trade(start + timedelta(days=1), 1.0),
            trade(start + timedelta(days=3), 2.0),
            trade(start + timedelta(days=9), -1.0),
            trade(start + timedelta(days=12), -1.0),
            trade(start + timedelta(days=20), 1.0),
        ]
        summary = rolling_windows(
            trades, start, start + timedelta(days=28), WalkForwardSettings(window_days=14, step_days=7)
        )
        assert [w.metrics.trades for w in summary.windows] == [4, 3, 1]
        assert summary.windows_with_trades == 3 and summary.windows_positive == 2
        assert summary.share_positive == pytest.approx(2 / 3)

    def test_no_window_without_a_trade_is_called_positive(self) -> None:
        start = datetime(2026, 11, 2, tzinfo=UTC)
        summary = rolling_windows([], start, start + timedelta(days=28), WalkForwardSettings())
        assert summary.windows_with_trades == 0 and summary.share_positive is None


# ------------------------------------------------------------------------------------------------------ replay and report

CONFIG = S01Config(
    symbols=("EURUSD",), swing_lookback=1, equal_level_tolerance=0.3, min_fvg_size=0.2, spread_buffer=0.05,
    reaction_window_m1_bars=8, act_within=timedelta(minutes=3),
)  # fmt: skip
COSTS = TradeCosts(spread=0.1, commission=0.02, stop_slippage=0.0)


def m1(i: int, c: Candle) -> Candle:
    return c.model_copy(update={"symbol": "EURUSD", "timeframe": Timeframe.M1})


def earlier(candles: list[Candle], step: timedelta) -> list[Candle]:
    """The scenario's higher-timeframe series, re-timed to a few days before the M1 candles so each bar has closed by then."""
    first = datetime(2026, 1, 5, tzinfo=UTC) - timedelta(days=10)
    return [c.model_copy(update={"open_time": first + i * step}) for i, c in enumerate(candles)]


def scenario_set(extra: list[Candle] | None = None) -> CandleSet:
    # three calm candles between the context and the reaction, so the reaction window (eight bars) splits exactly where the scenario does
    calm = [
        CONTEXT[-1].model_copy(update={"open_time": CONTEXT[-1].open_time + timedelta(minutes=i + 1)}) for i in range(3)
    ]
    reaction = [c.model_copy(update={"open_time": c.open_time + timedelta(minutes=3)}) for c in REACTION]
    base = [m1(i, c) for i, c in enumerate([*CONTEXT, *calm, *reaction])]
    return CandleSet(
        m1=[*base, *(extra or [])], h1=earlier(H1_DISCOUNT, timedelta(hours=1)),
        h4=earlier(BULLISH_HTF, timedelta(hours=4)), d1=earlier(BULLISH_HTF, timedelta(days=1)),
    )  # fmt: skip


def window(candles: list[Candle]) -> tuple[datetime, datetime]:
    return candles[0].open_time, candles[-1].open_time + timedelta(minutes=1)


def replayed(extra: list[Candle] | None = None, **changes: object):  # type: ignore[no-untyped-def]
    data = scenario_set(extra)
    start, end = window(data.m1)
    args: dict[str, object] = {
        "symbol": "EURUSD", "config": CONFIG, "variant": S01_VARIANT, "start": start, "end": end, "costs": COSTS,
        "cost_threshold": 0.25,
    }  # fmt: skip
    args.update(changes)
    return data, replay(data, **args)  # type: ignore[arg-type]


def test_the_replay_finds_the_setup_once_and_counts_where_the_others_stopped() -> None:
    data, result = replayed()
    assert len(result.proposals) == 1 and result.stale == 0
    assert result.proposals[0].spec.side is Side.BUY and result.evaluated == len(data.m1)
    assert (
        sum(result.stage_counts.values()) == result.evaluated - 1
    )  # every other candle stopped somewhere, and is counted
    assert result.proposals[0].spec.placed_at == data.m1[-1].open_time + timedelta(minutes=1)


def test_a_setup_seen_too_late_is_stale_not_taken() -> None:
    # the displacement is one minute old when its own candle closes: with a 10-second allowance it is a measurement, never an order
    _, result = replayed(config=CONFIG.model_copy(update={"act_within": timedelta(seconds=10)}))
    assert result.proposals == [] and result.stale == 1


def test_outside_the_trading_windows_nothing_is_evaluated() -> None:
    data = scenario_set()
    later = data.m1[0].open_time + timedelta(days=30, hours=8)
    result = replay(
        data, symbol="EURUSD", config=CONFIG, variant=S01_VARIANT, start=later, end=later + timedelta(hours=1), costs=COSTS,
        cost_threshold=0.25,
    )  # fmt: skip
    assert result.evaluated == 0 and result.proposals == []


def settings(**changes: object) -> RunSettings:
    data = scenario_set()
    start, end = window(data.m1)
    base: dict[str, object] = {
        "strategy_id": "S01", "strategy_version": "1", "symbol": "EURUSD", "start": start,
        "end": end + timedelta(hours=1), "config": CONFIG, "costs": COSTS, "cost_threshold": 0.25,
        "monte_carlo": MonteCarloSettings(risk_percent=1.0, paths=200, horizon_days=5),
    }  # fmt: skip
    base.update(changes)
    return RunSettings(**base)


def follow_up(entry: float, target: float, after: Candle) -> list[Candle]:
    """Two candles after the displacement: price comes back to the limit, then runs to the target."""
    t = after.open_time
    return [
        m1(0, after.model_copy(update={"open_time": t + timedelta(minutes=1), "high": entry + 0.1, "low": entry - 0.3, "open": entry, "close": entry})),
        m1(0, after.model_copy(update={"open_time": t + timedelta(minutes=2), "high": target + 1, "low": entry, "open": entry, "close": target})),
    ]  # fmt: skip


def test_a_full_run_replays_simulates_and_reports_honestly() -> None:
    _, first = replayed()
    spec = first.proposals[0].spec
    extra = follow_up(spec.entry, spec.target, scenario_set().m1[-1])
    report = run_validation(scenario_set(extra), settings(), S01_VARIANT, now=datetime(2026, 11, 3, tzinfo=UTC))
    assert report.proposals == 1 and report.orders.filled == 1 and report.outcomes == {"target": 1}
    assert report.metrics.trades == 1 and report.metrics.wins == 1 and report.metrics.expectancy_r is not None
    assert report.metrics.expectancy_r > 2.5  # the target is more than 3 R away, minus the commission
    assert report.monte_carlo is not None and report.monte_carlo.days_sampled == 1
    assert any("below the" in w for w in report.warnings)  # one trade proves nothing, and the report says so
    assert len(report.fingerprint) == 16 and report.assumptions and report.not_modelled


def test_the_fingerprint_names_the_rules_not_the_period() -> None:
    a, b = settings(), settings(end=settings().end + timedelta(days=5))
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint(settings(cost_threshold=0.3))
    assert fingerprint(a) != fingerprint(settings(costs=TradeCosts(spread=0.2, commission=0.02)))
    s02 = S02Config(**CONFIG.model_dump())
    assert fingerprint(a) != fingerprint(settings(strategy_id="S02", config=s02))
    assert s02_variant(s02) is not S01_VARIANT


def test_every_look_at_the_same_data_is_counted_and_reported() -> None:
    first = run_validation(scenario_set(), settings(), S01_VARIANT, now=datetime(2026, 11, 3, tzinfo=UTC))
    entry = ledger_entry(first)
    assert previous_looks([], settings()) == 0 and first.previous_looks == 0
    assert previous_looks([entry], settings()) == 1
    elsewhere = settings(symbol="GBPUSD")
    assert previous_looks([entry], elsewhere) == 0
    later = settings(start=settings().end + timedelta(days=1), end=settings().end + timedelta(days=3))
    assert previous_looks([entry], later) == 0  # a period nobody has read yet
    second = run_validation(
        scenario_set(), settings(), S01_VARIANT, now=datetime(2026, 11, 4, tzinfo=UTC), ledger=[entry]
    )
    assert second.previous_looks == 1 and any("already read" in w for w in second.warnings)
