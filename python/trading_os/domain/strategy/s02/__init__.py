"""S02 — the ICT 2022 strategy (ADR 0024): the pipeline of S01 recomposed with a bias read on H4 + H1, and a limit entry placed in the
zone of interest. Same detectors, same gates; nothing here is a new figure."""

from __future__ import annotations

from trading_os.domain.strategy.s02.config import S02Config
from trading_os.domain.strategy.s02.pipeline import evaluate_setup_s02, s02_variant

__all__ = ["S02Config", "evaluate_setup_s02", "s02_variant"]
