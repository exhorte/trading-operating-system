"""S02's sequence: H4+H1 bias → 1H dealing range → liquidity → sweep → displacement/MSS → POI (FVG, else order block) → stop → viability
gates → a proposal whose entry is a limit order in the zone. It is S01's ``evaluate_setup`` with another bias and another proposal prefix."""

from __future__ import annotations

from trading_os.domain.primitives import Bias
from trading_os.domain.strategy.s01.bias import agreed_bias
from trading_os.domain.strategy.s01.models import BlockedOutcome, ProposedOutcome
from trading_os.domain.strategy.s01.proposal import SetupProposalInput, Variant, evaluate_setup
from trading_os.domain.strategy.s02.config import S02Config

S02_ID_PREFIX = "setup-s02"


def _h4_h1_bias(setup: SetupProposalInput) -> Bias:
    return agreed_bias(setup.h4_candles, setup.h1_candles, setup.swing_lookback)


def s02_variant(config: S02Config) -> Variant:
    return Variant(
        bias=_h4_h1_bias,
        bias_detail="H4/H1 disagree or show no confirmed structure",
        entry_fraction=config.entry_fraction,
        id_prefix=S02_ID_PREFIX,
        use_map_timeframe=True,
        poi_location=True,
        target_beyond_equilibrium=True,
        entry_spread_offset=True,
    )


def evaluate_setup_s02(setup: SetupProposalInput, config: S02Config) -> BlockedOutcome | ProposedOutcome:
    return evaluate_setup(setup, s02_variant(config))
