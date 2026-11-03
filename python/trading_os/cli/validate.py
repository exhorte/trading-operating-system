"""``validate`` — the validation bench from the command line (ADR 0026): one strategy, one frozen configuration, one past period.

Reads the candles already in the database, writes a JSON report and a Markdown summary, and appends one line to the ledger of looks
(``exports/validation/ledger.jsonl``) so that reading the same data again and again is visible in the next report. It touches no account,
sends nothing, and offers no way to compare configurations.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from trading_os.domain.market.models import Candle
from trading_os.domain.positions.manager import SymbolConstraints
from trading_os.domain.primitives import Timeframe
from trading_os.domain.strategy.s01.config import S01Config
from trading_os.domain.strategy.s01.proposal import S01_VARIANT, Variant
from trading_os.domain.strategy.s02 import S02Config, s02_variant
from trading_os.domain.validation.metrics import Metrics
from trading_os.domain.validation.montecarlo import MonteCarloSettings
from trading_os.domain.validation.replay import CandleSet
from trading_os.domain.validation.report import RunSettings, ValidationReport, ledger_entry, run_validation
from trading_os.domain.validation.simulate import SimulationSettings, TradeCosts
from trading_os.shared.errors import ValidationFailed

LEDGER_NAME = "ledger.jsonl"
# How far before the period each timeframe must reach for the strategy to have its context (bars read per timeframe in S01Config).
PAD_BEFORE = {
    Timeframe.M1: timedelta(days=2),
    Timeframe.M15: timedelta(days=8),
    Timeframe.H1: timedelta(days=30),
    Timeframe.H4: timedelta(days=90),
    Timeframe.D1: timedelta(days=400),
}
TAIL_AFTER = timedelta(hours=8)  # an order placed at the end of the period still has time to play out


def strategy_definition(strategy_id: str) -> tuple[S01Config, Variant, str]:
    if strategy_id == "S01":
        return S01Config(), S01_VARIANT, "1"
    if strategy_id == "S02":
        config = S02Config()
        return config, s02_variant(config), "1"
    raise ValidationFailed(f"unknown strategy {strategy_id!r}: S01 or S02", code="unknown_strategy")


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def append_ledger(path: Path, report: ValidationReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ledger_entry(report), sort_keys=True) + "\n")


async def load_candles(repos: Any, symbol: str, start: datetime, end: datetime) -> CandleSet:
    async def closed(timeframe: Timeframe) -> list[Candle]:
        found = await repos.market.candles(symbol, timeframe, start - PAD_BEFORE[timeframe], end + TAIL_AFTER)
        return [c for c in found if c.closed]

    return CandleSet(
        m1=await closed(Timeframe.M1),
        m15=await closed(Timeframe.M15),
        h1=await closed(Timeframe.H1),
        h4=await closed(Timeframe.H4),
        d1=await closed(Timeframe.D1),
    )


def build_settings(
    *, strategy_id: str, symbol: str, start: datetime, end: datetime, costs: TradeCosts, risk_percent: float,
    cost_threshold: float, digits: int,
) -> tuple[RunSettings, Variant]:  # fmt: skip
    config, variant, version = strategy_definition(strategy_id)
    settings = RunSettings(
        strategy_id=strategy_id, strategy_version=version, symbol=symbol, start=start, end=end, config=config, costs=costs,
        cost_threshold=cost_threshold,
        simulation=SimulationSettings(
            constraints=SymbolConstraints(volume_step=0.01, volume_min=0.01, price_decimals=digits)
        ),
        monte_carlo=MonteCarloSettings(risk_percent=risk_percent),
    )  # fmt: skip
    return settings, variant


def _line(name: str, m: Metrics) -> str:
    def f(value: float | None, digits: int = 2) -> str:
        return "—" if value is None else f"{value:.{digits}f}"

    return (
        f"| {name} | {m.trades} | {f(m.win_rate and m.win_rate * 100, 0)} % | {f(m.expectancy_r)} | {f(m.profit_factor)} | "
        f"{f(m.total_r)} | {f(m.max_drawdown_r)} | {m.longest_losing_streak} |"
    )


def render_markdown(report: ValidationReport) -> str:
    out = [
        f"# Validation {report.strategy_id} v{report.strategy_version} — {report.symbol}",
        "",
        f"Période {report.period_start:%Y-%m-%d %H:%M} → {report.period_end:%Y-%m-%d %H:%M} UTC · configuration `{report.fingerprint}` · "
        f"lectures antérieures de ces données : **{report.previous_looks}**",
        "",
    ]
    if report.warnings:
        out += ["## À lire d'abord", "", *[f"- {w}" for w in report.warnings], ""]
    o = report.orders
    out += [
        "## Ce que la machine a vu",
        "",
        f"- {report.evaluated_candles} bougies évaluées ({report.skipped_outside_windows} hors fenêtre) · {report.proposals} proposition(s) "
        f"agissable(s) · {report.stale_proposals} vue(s) trop tard",
        f"- ordres : {o.filled} exécuté(s), {o.unfilled} jamais touché(s), {o.expired} expiré(s), {o.invalidated} invalidé(s) avant d'être touchés",
        "- où les autres bougies se sont arrêtées : "
        + (", ".join(f"{k} {v}" for k, v in report.stage_counts.items()) or "—"),
        "",
        "## Résultat (en R, coûts compris)",
        "",
        "| Ensemble | Trades | Gagnants | Espérance R | Facteur de profit | Total R | Drawdown max R | Pire série |",
        "|---|---|---|---|---|---|---|---|",
        _line("Tous", report.metrics),
        *[_line(f"Fenêtre {k}", v) for k, v in report.by_window.items()],
        *[_line(f"Jour {k}", v) for k, v in report.by_weekday.items()],
        "",
        "## Stabilité (mêmes règles, fenêtres successives)",
        "",
        f"{report.stability.windows_positive} fenêtre(s) positive(s) sur {report.stability.windows_with_trades} qui ont des trades.",
        "",
    ]
    if report.monte_carlo is not None:
        mc = report.monte_carlo
        out += [
            "## Monte Carlo (journées tirées avec remise)",
            "",
            f"{mc.paths} trajectoires de {mc.horizon_days} jours à {mc.risk_percent:g} % par trade, graine {mc.seed}, "
            f"{mc.days_sampled} journée(s) tirée(s) :",
            "",
            f"- limite journalière atteinte dans **{mc.p_daily_breach:.1%}** des trajectoires, limite totale dans **{mc.p_total_breach:.1%}**",
            f"- rendement final (% du capital) : p5 {mc.return_p05:+.2f} · médiane {mc.return_p50:+.2f} · p95 {mc.return_p95:+.2f}",
            f"- drawdown maximal (%) : médiane {mc.max_drawdown_p50:.2f} · p95 {mc.max_drawdown_p95:.2f}",
            "",
        ]
    out += [
        "## Hypothèses",
        "",
        *[f"- {a}" for a in report.assumptions],
        "",
        "## Non modélisé",
        "",
        *[f"- {n}" for n in report.not_modelled],
    ]
    out += ["", "Une mesure sur un échantillon passé n'est ni une preuve ni une prévision.", ""]
    return "\n".join(out)


def write_outputs(report: ValidationReport, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"validation-{report.strategy_id}-{report.symbol}-{report.period_start:%Y%m%d}-{report.period_end:%Y%m%d}-{report.fingerprint}"
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    json_path.write_text(report.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


async def validate(
    repos: Any, *, settings: RunSettings, variant: Variant, out_dir: Path, now: datetime,
) -> tuple[ValidationReport, Sequence[Path]]:  # fmt: skip
    candles = await load_candles(repos, settings.symbol, settings.start, settings.end)
    if not candles.m1:
        raise ValidationFailed(
            f"no M1 candle of {settings.symbol} in the database for this period (import-candles or export-history first)",
            code="no_candles",
        )
    ledger_path = out_dir / LEDGER_NAME
    report = run_validation(candles, settings, variant, now=now, ledger=read_ledger(ledger_path))
    json_path, md_path = write_outputs(report, out_dir)
    append_ledger(ledger_path, report)
    return report, (json_path, md_path)
