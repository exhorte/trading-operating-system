"""
T02b/T05 verification (quality_gates.md: new domain logic needs a test).
Stdlib `unittest` only — no pytest dependency in this repo. Run with:
    python -m unittest tools/mt5-observer/test_mt5_observer.py

Covers: the T02b pitfall (a partially-closed position must be judged by the
SUM of every deal, never a single deal in isolation); T05's opened/closed
diff (a position lifecycle event must fire exactly once, and never on boot);
T05 review fixes — identifier vs ticket as the position key, and a position
that opens AND closes between two polls (scan_missed_round_trips).
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import MetaTrader5 as mt5

import mt5_observer as observer


def deal(entry, type_, volume, profit, commission, swap, time, symbol="XAUUSDm", price=0.0, position_id=0):
    return SimpleNamespace(
        entry=entry, type=type_, volume=volume, profit=profit,
        commission=commission, swap=swap, time=time, symbol=symbol, price=price,
        position_id=position_id,
    )


def position(identifier, symbol, type_, volume, price_open, sl, tp, profit=0.0, ticket=None):
    # `ticket` defaults to `identifier` (the common case where they coincide);
    # pass it explicitly to test the case where they diverge — the exact
    # MT5 pitfall flagged in review (ticket can be rewritten by broker-side
    # service operations, identifier cannot).
    return SimpleNamespace(
        identifier=identifier, ticket=ticket if ticket is not None else identifier,
        symbol=symbol, type=type_, volume=volume,
        price_open=price_open, sl=sl, tp=tp, profit=profit,
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


class WeightedExitPriceTests(unittest.TestCase):
    def test_volume_weights_the_average_across_partial_exits(self):
        exit_deals = [
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=5.00, commission=-0.10, swap=0, time=1_010, price=4055.0),
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.03, profit=0.05, commission=-0.10, swap=-0.20, time=1_020, price=4053.0),
        ]
        # (4055*0.01 + 4053*0.03) / 0.04 = 4053.5
        self.assertEqual(observer.weighted_exit_price(exit_deals), 4053.5)

    def test_single_exit_deal_is_just_its_price(self):
        exit_deals = [deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_SELL, 0.02, profit=-3.0, commission=-0.1, swap=0, time=2_010, price=4040.0)]
        self.assertEqual(observer.weighted_exit_price(exit_deals), 4040.0)


class BuildPositionClosedTests(unittest.TestCase):
    def test_maps_side_symbol_volume_exit_price_and_closed_at_from_the_deal_history(self):
        deals = [
            deal(mt5.DEAL_ENTRY_IN, mt5.DEAL_TYPE_BUY, 0.02, profit=0, commission=-0.20, swap=0, time=1_000, symbol="XAUUSDm", price=4050.0),
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=5.00, commission=-0.10, swap=0, time=1_010, price=4055.0),
            deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=0.05, commission=-0.10, swap=-0.20, time=1_020, price=4053.0),
        ]
        msg = observer.build_position_closed(12345, deals)
        assert msg is not None
        self.assertEqual(msg["type"], "position.closed")
        self.assertEqual(msg["brokerPositionId"], "12345")
        self.assertEqual(msg["symbol"], "XAUUSDm")
        self.assertEqual(msg["side"], "BUY")
        self.assertEqual(msg["volume"], 0.02)
        self.assertEqual(msg["realizedPnl"], 4.45)
        self.assertEqual(msg["exitPrice"], 4054.0)  # (4055*0.01+4053*0.01)/0.02
        self.assertEqual(msg["closedAt"], 1_020_000)  # last exit deal, epoch ms

    def test_none_when_deal_history_is_incomplete(self):
        # Only an entry deal on record (e.g. history not synced yet) — never
        # emit a half-known fact.
        deals = [deal(mt5.DEAL_ENTRY_IN, mt5.DEAL_TYPE_BUY, 0.02, profit=0, commission=0, swap=0, time=1_000)]
        self.assertIsNone(observer.build_position_closed(12345, deals))
        self.assertIsNone(observer.build_position_closed(12345, []))


class BuildPositionOpenedTests(unittest.TestCase):
    def test_maps_fields_from_the_live_position(self):
        p = position(555, "XAUUSDm", mt5.POSITION_TYPE_SELL, 0.05, 4060.0, 4070.0, 4030.0)
        msg = observer.build_position_opened(p)
        self.assertEqual(msg["type"], "position.opened")
        self.assertEqual(msg["brokerPositionId"], "555")
        self.assertEqual(msg["side"], "SELL")
        self.assertEqual(msg["entryPrice"], 4060.0)
        self.assertEqual(msg["stopLoss"], 4070.0)
        self.assertEqual(msg["takeProfit"], 4030.0)

    def test_uses_identifier_not_ticket_when_they_diverge(self):
        # The exact pitfall flagged in review: identifier is POSITION_IDENTIFIER
        # (stable for the position's whole life); ticket is the opening
        # order's ticket and can be rewritten by broker-side service
        # operations. Keying on ticket would silently corrupt lifecycle
        # tracking the day they diverge on a still-open position.
        p = position(identifier=999, ticket=111, symbol="XAUUSDm", type_=mt5.POSITION_TYPE_BUY,
                     volume=0.01, price_open=100.0, sl=90.0, tp=110.0)
        msg = observer.build_position_opened(p)
        self.assertEqual(msg["brokerPositionId"], "999")
        self.assertNotEqual(msg["brokerPositionId"], "111")


class MapPositionTests(unittest.TestCase):
    def test_positions_snapshot_keys_on_identifier_not_ticket(self):
        p = position(identifier=999, ticket=111, symbol="XAUUSDm", type_=mt5.POSITION_TYPE_BUY,
                     volume=0.01, price_open=100.0, sl=90.0, tp=110.0)
        mapped = observer._map_position(p)
        self.assertEqual(mapped["brokerPositionId"], "999")


class BuildPositionOpenedFromDealTests(unittest.TestCase):
    def test_maps_from_the_entry_deal_alone_with_unknown_sl_tp(self):
        entry = deal(mt5.DEAL_ENTRY_IN, mt5.DEAL_TYPE_SELL, 0.02, profit=0, commission=-0.2, swap=0,
                     time=1_500, symbol="XAUUSDm", price=4070.0)
        msg = observer.build_position_opened_from_deal(777, entry)
        self.assertEqual(msg["brokerPositionId"], "777")
        self.assertEqual(msg["side"], "SELL")
        self.assertEqual(msg["entryPrice"], 4070.0)
        self.assertEqual(msg["stopLoss"], 0.0)
        self.assertEqual(msg["takeProfit"], 0.0)
        self.assertEqual(msg["openedAt"], 1_500_000)  # real MT5 deal time, not detection time


class ScanMissedRoundTripsTests(unittest.TestCase):
    def setUp(self):
        # An open scan window (5s in the past) unless a test overrides it.
        observer._last_deal_scan_ms = observer.now_ms() - 5_000

    def test_reconstructs_a_position_that_opened_and_closed_between_polls(self):
        entry = deal(mt5.DEAL_ENTRY_IN, mt5.DEAL_TYPE_BUY, 0.01, profit=0, commission=-0.1, swap=0,
                     time=1_000, price=4050.0, position_id=777)
        exit_ = deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=2.0, commission=-0.1, swap=0,
                     time=1_005, price=4052.0, position_id=777)

        def fake_history_deals_get(*args, **kwargs):
            if "position" in kwargs:
                return (entry, exit_) if kwargs["position"] == 777 else ()
            return (exit_,)  # the date-range scan only needs to see the exit

        with mock.patch.object(observer.mt5, "history_deals_get", side_effect=fake_history_deals_get):
            opened, closed = observer.scan_missed_round_trips(known_before_this_poll=set(), current_ids=set())

        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["brokerPositionId"], "777")
        self.assertEqual(opened[0]["entryPrice"], 4050.0)
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["brokerPositionId"], "777")
        self.assertEqual(closed[0]["realizedPnl"], 1.8)

    def test_ignores_a_position_already_covered_by_the_normal_diff(self):
        exit_ = deal(mt5.DEAL_ENTRY_OUT, mt5.DEAL_TYPE_BUY, 0.01, profit=1.0, commission=0, swap=0,
                     time=1_000, position_id=42)

        with mock.patch.object(observer.mt5, "history_deals_get", return_value=(exit_,)) as mocked:
            # Already known before this poll -> the ordinary closed_ids path handles it.
            opened, closed = observer.scan_missed_round_trips(known_before_this_poll={42}, current_ids=set())
            self.assertEqual((opened, closed), ([], []))

            # Still open right now -> a partial close, not a full round trip.
            opened, closed = observer.scan_missed_round_trips(known_before_this_poll=set(), current_ids={42})
            self.assertEqual((opened, closed), ([], []))
        # Confirms these are cheap early-outs, not accidentally correct via mocking.
        self.assertTrue(mocked.called)

    def test_returns_nothing_when_the_scan_window_is_empty(self):
        observer._last_deal_scan_ms = observer.now_ms() + 10_000  # since >= until
        with mock.patch.object(observer.mt5, "history_deals_get") as mocked:
            opened, closed = observer.scan_missed_round_trips(set(), set())
        self.assertEqual((opened, closed), ([], []))
        mocked.assert_not_called()


class PollPositionsIdentifierTests(unittest.TestCase):
    def test_diffs_on_identifier_not_ticket(self):
        # Regression for the review finding: a ticket/identifier mismatch
        # must not be visible as a false close + false open.
        p = position(identifier=42, ticket=100, symbol="XAUUSDm", type_=mt5.POSITION_TYPE_BUY,
                     volume=0.01, price_open=4000.0, sl=3990.0, tp=4010.0)
        observer._known_position_ids = set()
        observer._last_deal_scan_ms = observer.now_ms()

        with mock.patch.object(observer.mt5, "positions_get", return_value=(p,)), \
             mock.patch.object(observer.mt5, "history_deals_get", return_value=()):
            _, opened, closed = observer.poll_positions("XAUUSDm")

        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0]["brokerPositionId"], "42")
        self.assertEqual(closed, [])
        self.assertIn(42, observer._known_position_ids)
        self.assertNotIn(100, observer._known_position_ids)


class DiffPositionIdsTests(unittest.TestCase):
    def test_detects_both_sides_of_one_comparison(self):
        opened, closed = observer.diff_position_ids(known_ids={1, 2}, current_ids={2, 3})
        self.assertEqual(opened, {3})
        self.assertEqual(closed, {1})

    def test_no_changes_when_the_set_is_unchanged(self):
        opened, closed = observer.diff_position_ids(known_ids={1, 2}, current_ids={1, 2})
        self.assertEqual(opened, set())
        self.assertEqual(closed, set())

    def test_a_baseline_read_must_seed_not_diff(self):
        # This is exactly the trap: naively diffing against an empty
        # known_ids on the very first read would report every pre-existing
        # position as "opened". seed_known_positions exists so callers never
        # pass an empty known_ids into diff_position_ids for a first read.
        opened, closed = observer.diff_position_ids(known_ids=set(), current_ids={1, 2, 3})
        self.assertEqual(opened, {1, 2, 3})  # correct behavior of the pure diff...
        self.assertEqual(closed, set())
        # ...which is exactly why seed_known_positions never calls this function.


class AccessCheckTests(unittest.TestCase):
    """I0 (2026-09-26): the stream carries the account; any container reaches
    127.0.0.1:8765 through host.docker.internal. Only the backend's token
    opens it, and a browser never does."""

    TOKEN = "obs-Token_123"

    def check(self, **headers):
        from websockets.datastructures import Headers

        connection = SimpleNamespace(respond=lambda status, text: ("refused", int(status), text))
        request = SimpleNamespace(headers=Headers(**headers) if headers else Headers())
        return observer.make_access_check(self.TOKEN)(connection, request)

    def check_raw(self, pairs):
        from websockets.datastructures import Headers

        connection = SimpleNamespace(respond=lambda status, text: ("refused", int(status), text))
        return observer.make_access_check(self.TOKEN)(connection, SimpleNamespace(headers=Headers(pairs)))

    def test_the_backend_token_opens_the_stream(self):
        self.assertIsNone(self.check(Authorization=f"Bearer {self.TOKEN}"))

    def test_missing_or_wrong_token_is_refused(self):
        self.assertEqual(self.check()[1], 403)
        self.assertEqual(self.check(Authorization="Bearer nope")[1], 403)
        self.assertEqual(self.check(Authorization=self.TOKEN)[1], 403)
        self.assertEqual(self.check(Authorization=f"Bearer {self.TOKEN}x")[1], 403)

    def test_a_browser_is_refused_even_with_the_token(self):
        refused = self.check(Authorization=f"Bearer {self.TOKEN}", Origin="http://localhost:3000")
        self.assertEqual(refused[1], 403)
        self.assertNotIn(self.TOKEN, refused[2])

    def test_two_authorization_headers_are_refused(self):
        refused = self.check_raw([("Authorization", f"Bearer {self.TOKEN}"), ("Authorization", "Bearer x")])
        self.assertEqual(refused[1], 403)

    def test_a_real_handshake_goes_through_only_with_the_token(self):
        import asyncio

        import websockets
        from websockets.exceptions import InvalidStatus

        async def scenario():
            async def handler(ws):
                await ws.send("hello")

            async with websockets.serve(handler, "127.0.0.1", 0, process_request=observer.make_access_check(self.TOKEN)) as server:
                port = server.sockets[0].getsockname()[1]
                uri = f"ws://127.0.0.1:{port}"
                async with websockets.connect(uri, additional_headers={"Authorization": f"Bearer {self.TOKEN}"}) as ws:
                    self.assertEqual(await ws.recv(), "hello")
                with self.assertRaises(InvalidStatus) as refused:
                    async with websockets.connect(uri):
                        pass
                self.assertEqual(refused.exception.response.status_code, 403)
                with self.assertRaises(InvalidStatus):
                    async with websockets.connect(uri, additional_headers={"Authorization": "Bearer wrong"}):
                        pass
                with self.assertRaises(InvalidStatus):
                    async with websockets.connect(
                        uri, origin="http://localhost:3000",
                        additional_headers={"Authorization": f"Bearer {self.TOKEN}"},
                    ):
                        pass

        asyncio.run(scenario())


class BuildAccountTests(unittest.TestCase):
    """I2 (2026-09-26): the account as MT5's account window shows it — never
    the holder's name (personal data; envelopes are persisted, ADR 0009)."""

    def account(self, **overrides):
        values = dict(
            login=477029930, name="Jeanne Titulaire", server="Exness-MT5Trial9",
            company="Exness Technologies Ltd", currency="USD", balance=1046.84, equity=1046.84,
            margin=0.0, margin_free=1046.84, margin_level=0.0, leverage=2000,
            trade_mode=0, margin_mode=2, fifo_close=False, trade_allowed=True, trade_expert=True,
        )
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_publishes_the_account_window_and_never_the_name(self):
        with mock.patch.object(observer.mt5, "account_info", return_value=self.account()):
            msg = observer.build_account()
        self.assertNotIn("name", msg)
        self.assertNotIn("Jeanne Titulaire", repr(msg))
        self.assertEqual(msg["accountId"], "477029930")
        self.assertEqual(msg["tradeMode"], "demo")
        self.assertEqual(msg["marginMode"], "hedging")
        self.assertEqual(msg["leverage"], 2000)
        self.assertEqual(msg["server"], "Exness-MT5Trial9")
        self.assertIs(msg["tradeAllowed"], True)
        self.assertIsNone(msg["marginLevel"])  # no margin used: unknown, never 0

    def test_real_netting_and_an_investor_password(self):
        with mock.patch.object(observer.mt5, "account_info",
                               return_value=self.account(trade_mode=2, margin_mode=0, margin=10.0,
                                                         margin_level=10468.4, trade_allowed=False)):
            msg = observer.build_account()
        self.assertEqual(msg["tradeMode"], "real")
        self.assertEqual(msg["marginMode"], "netting")
        self.assertEqual(msg["marginLevel"], 10468.4)
        self.assertIs(msg["tradeAllowed"], False)

    def test_a_login_change_is_detected_only_against_the_starting_login(self):
        with mock.patch.object(observer, "_started_login", None):
            self.assertFalse(observer.login_changed(123))
        with mock.patch.object(observer, "_started_login", 123):
            self.assertFalse(observer.login_changed(123))
            self.assertFalse(observer.login_changed(None))
            self.assertTrue(observer.login_changed(456))


class ObserverTokenSourceTests(unittest.TestCase):
    def write_env(self, text, bom=False):
        import tempfile
        from pathlib import Path

        handle = tempfile.NamedTemporaryFile("wb", suffix=".env", delete=False)
        handle.write((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_reads_its_own_line_and_nothing_else(self):
        path = self.write_env("# comment\nFRED_API_KEY=other-secret\n\nTRADINGOS_OBSERVER_TOKEN=abc\n", bom=True)
        self.assertEqual(observer.read_env_value(path, "TRADINGOS_OBSERVER_TOKEN"), "abc")
        self.assertIsNone(observer.read_env_value(path, "TRADINGOS_COCKPIT_TOKEN"))

    def test_empty_value_or_missing_file_is_no_token(self):
        from pathlib import Path

        self.assertIsNone(observer.read_env_value(self.write_env("TRADINGOS_OBSERVER_TOKEN=\n"), "TRADINGOS_OBSERVER_TOKEN"))
        self.assertIsNone(observer.read_env_value(Path("does-not-exist.env"), "TRADINGOS_OBSERVER_TOKEN"))

    def test_the_environment_wins_over_the_file(self):
        path = self.write_env("TRADINGOS_OBSERVER_TOKEN=from-file\n")
        self.assertEqual(observer.load_observer_token({"TRADINGOS_OBSERVER_TOKEN": "from-env"}, path), "from-env")
        self.assertEqual(observer.load_observer_token({}, path), "from-file")


if __name__ == "__main__":
    unittest.main()
