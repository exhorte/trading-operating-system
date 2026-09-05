"""
T02b verification (quality_gates.md: new domain logic needs a test). Stdlib
`unittest` only — no pytest dependency in this repo. Run with:
    python -m unittest tools/mt5-observer/test_mt5_observer.py

Covers the exact pitfall flagged in review: a partially-closed position must
be judged by the SUM of every deal, never a single deal in isolation.
"""

import unittest
from types import SimpleNamespace

import MetaTrader5 as mt5

import mt5_observer as observer


def deal(entry, type_, volume, profit, commission, swap, time, symbol="XAUUSDm"):
    return SimpleNamespace(
        entry=entry, type=type_, volume=volume, profit=profit,
        commission=commission, swap=swap, time=time, symbol=symbol,
    )


class SumRealizedPnlTests(unittest.TestCase):
    def test_net_winner_despite_a_negative_partial_exit(self):
        """One entry + two partial exits: the second exit alone is negative
        (after swap), but the position is a net winner. A single-deal check
        would misclassify it as a loser — the sum must not."""
        deals = [
            deal(mt5.DEAL_ENTRY_IN, mt5.DEAL_TYPE_BUY, 0.02, profit=0, commission=-0.20, swap=0, time=1_000),
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=5.00, commission=-0.10, swap=0, time=1_010),
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=0.05, commission=-0.10, swap=-0.20, time=1_020),
        ]
        last_deal_alone = deals[-1].profit + deals[-1].commission + deals[-1].swap
        self.assertLess(last_deal_alone, 0)  # confirms the trap is real

        net = observer.sum_realized_pnl(deals)
        self.assertEqual(net, 4.45)
        self.assertGreater(net, 0)  # correctly a winner overall

    def test_net_loser_stays_a_loser(self):
        deals = [
            deal(mt5.DEAL_ENTRY_IN, mt5.DEAL_TYPE_SELL, 0.01, profit=0, commission=-0.10, swap=0, time=2_000),
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_SELL, 0.01, profit=-3.00, commission=-0.10, swap=-0.05, time=2_010),
        ]
        self.assertEqual(observer.sum_realized_pnl(deals), -3.25)


class BuildPositionClosedTests(unittest.TestCase):
    def test_maps_side_symbol_volume_and_closed_at_from_the_deal_history(self):
        deals = [
            deal(mt5.DEAL_ENTRY_IN, mt5.DEAL_TYPE_BUY, 0.02, profit=0, commission=-0.20, swap=0, time=1_000, symbol="XAUUSDm"),
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=5.00, commission=-0.10, swap=0, time=1_010),
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=0.05, commission=-0.10, swap=-0.20, time=1_020),
        ]
        msg = observer.build_position_closed(12345, deals)
        assert msg is not None
        self.assertEqual(msg["type"], "position.closed")
        self.assertEqual(msg["brokerPositionId"], "12345")
        self.assertEqual(msg["symbol"], "XAUUSDm")
        self.assertEqual(msg["side"], "BUY")
        self.assertEqual(msg["volume"], 0.02)
        self.assertEqual(msg["realizedPnl"], 4.45)
        self.assertEqual(msg["closedAt"], 1_020_000)  # last exit deal, epoch ms

    def test_none_when_deal_history_is_incomplete(self):
        # Only an entry deal on record (e.g. history not synced yet) — never
        # emit a half-known fact.
        deals = [deal(mt5.DEAL_ENTRY_IN, mt5.DEAL_TYPE_BUY, 0.02, profit=0, commission=0, swap=0, time=1_000)]
        self.assertIsNone(observer.build_position_closed(12345, deals))
        self.assertIsNone(observer.build_position_closed(12345, []))


if __name__ == "__main__":
    unittest.main()
