"""Structural guarantees of the multi-environment design (ADR 0036): kept by a test so a refactor cannot quietly break them."""

from __future__ import annotations

import re

from tests.architecture.test_invariants import PACKAGE_ROOT, python_files


class TestObjectivesAreNeverAnInputToRisk:
    """« Les objectifs de profit FTMO ne sont pas des ordres de trading. Ils ne sont jamais une raison d'augmenter le risque. »

    The one module of the risk engine allowed to name them is the effective policy, which *lists* them as informational (its own
    unit test proves they are never active)."""

    TARGET_WORDS = re.compile(r"profit_target|min_trading_days")
    DISPLAY_ONLY = frozenset({"domain/risk/effective.py"})

    def test_nothing_in_the_risk_engine_the_execution_path_or_the_strategies_reads_a_profit_target(self) -> None:
        offenders = []
        for subdir in (
            "domain/risk",
            "domain/execution",
            "domain/strategy",
            "services/risk.py",
            "services/execution.py",
        ):
            target = PACKAGE_ROOT / subdir
            files = [target] if target.is_file() else python_files(subdir)
            for path in files:
                rel = path.relative_to(PACKAGE_ROOT).as_posix()
                if rel in self.DISPLAY_ONLY:
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if self.TARGET_WORDS.search(line.split("#", 1)[0]):
                        offenders.append(f"{rel}:{number}: {line.strip()}")
        assert not offenders, "\n".join(offenders)


class TestEveryRuleCarriesItsProvenance:
    def test_every_provider_rule_set_has_a_dated_source(self) -> None:
        from trading_os.domain.providers.rules import RULE_SETS

        for rule_set in RULE_SETS:
            assert rule_set.sources, rule_set.rule_set_id
            for source in rule_set.sources:
                assert source.retrieved_on is not None
