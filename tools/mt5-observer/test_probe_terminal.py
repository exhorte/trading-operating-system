"""
T12 incrément 2 — the observer must start on the gold symbol its terminal
lists. Stdlib `unittest` only, like test_mt5_observer.py. Run with:
    python -m unittest tools/mt5-observer/test_probe_terminal.py
"""

import unittest

import probe_terminal as probe


class DetectFirmTests(unittest.TestCase):
    def test_recognises_each_firm_whatever_the_case(self):
        self.assertEqual(probe.detect_firm("FTMO Global Markets Ltd"), "ftmo")
        self.assertEqual(probe.detect_firm("Exness Technologies Ltd"), "exness")

    def test_recognises_nothing_it_has_no_rule_for(self):
        self.assertIsNone(probe.detect_firm("Some Other Broker"))
        self.assertIsNone(probe.detect_firm(None))


class ChooseGoldSymbolTests(unittest.TestCase):
    def test_ftmo_observes_the_canonical_name(self):
        self.assertEqual(probe.choose_gold_symbol("ftmo", {"XAUUSD": True, "XAUUSDm": False}), "XAUUSD")

    def test_exness_observes_the_suffixed_name(self):
        self.assertEqual(probe.choose_gold_symbol("exness", {"XAUUSD": False, "XAUUSDm": True}), "XAUUSDm")

    def test_a_recognised_firm_missing_its_own_name_is_reported_not_substituted(self):
        # Observing XAUUSD on an Exness terminal would be another instrument
        # than the one the spread gate is calibrated for — None, not a guess.
        self.assertIsNone(probe.choose_gold_symbol("exness", {"XAUUSD": True, "XAUUSDm": False}))

    def test_an_unrecognised_broker_takes_whichever_known_name_exists(self):
        self.assertEqual(probe.choose_gold_symbol(None, {"XAUUSD": False, "XAUUSDm": True}), "XAUUSDm")
        self.assertIsNone(probe.choose_gold_symbol(None, {"XAUUSD": False, "XAUUSDm": False}))


if __name__ == "__main__":
    unittest.main()
