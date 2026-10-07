from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from trading_os.app.config import Settings, TradingMode
from trading_os.shared.errors import Conflict, NotFound, TradingOsError
from trading_os.shared.events import EVENT_REGISTRY, Event, EventDispatcher
from trading_os.shared.ids import new_command_id, new_id
from trading_os.shared.logging import RedactingFormatter, redact, register_secret
from trading_os.shared.time import ManualClock, from_epoch_ms, iso, parse_iso, to_epoch_ms


class TestTime:
    def test_iso_is_utc_with_z_and_milliseconds(self) -> None:
        assert iso(datetime(2026, 10, 7, 12, 30, 15, 123456, tzinfo=UTC)) == "2026-10-07T12:30:15.123Z"

    def test_iso_rejects_naive_datetimes(self) -> None:
        with pytest.raises(ValueError):
            iso(datetime(2026, 10, 7, 12, 0))

    def test_parse_iso_round_trip_and_offsets(self) -> None:
        assert parse_iso("2026-10-07T12:00:00Z") == datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        assert parse_iso("2026-10-07T14:00:00+02:00") == datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
        with pytest.raises(ValueError):
            parse_iso("2026-10-07T12:00:00")

    def test_epoch_ms_round_trip(self) -> None:
        dt = datetime(2026, 10, 7, 12, 0, 1, 500000, tzinfo=UTC)
        assert from_epoch_ms(to_epoch_ms(dt)) == dt

    def test_manual_clock_advances(self) -> None:
        clock = ManualClock(datetime(2026, 1, 1, tzinfo=UTC))
        clock.advance(minutes=30)
        assert clock.now() == datetime(2026, 1, 1, 0, 30, tzinfo=UTC)


class TestIds:
    def test_prefixed_and_unique(self) -> None:
        a, b = new_id("evt"), new_id("evt")
        assert a.startswith("evt-") and len(a) == len("evt-") + 12
        assert a != b
        assert new_command_id().startswith("cmd-")


class TestErrors:
    def test_codes_and_status(self) -> None:
        assert NotFound("x").http_status == 404 and NotFound("x").code == "not_found"
        assert Conflict("x").http_status == 409
        assert TradingOsError("x", code="custom").code == "custom"

    def test_message_is_redacted_on_the_way_out(self) -> None:
        register_secret("s3cret-value")
        err = TradingOsError("login failed for s3cret-value")
        assert "s3cret-value" not in err.safe_message
        assert "s3cret-value" not in str(err.to_dict())


class TestRedaction:
    def test_registered_values_are_masked_anywhere(self) -> None:
        register_secret("hunter2-hunter2")
        assert redact("before hunter2-hunter2 after") == "before *** after"

    def test_shapes_are_masked_without_registration(self) -> None:
        assert redact("Authorization: Bearer abc.def-123") == "Authorization: Bearer ***"
        assert "abc123" not in redact("GET /ws?access_token=abc123&x=1")
        assert "p4ss" not in redact("password=p4ss")
        assert "p4ss" not in redact('{"password": "p4ss"}')

    def test_short_secrets_are_ignored_not_over_masking(self) -> None:
        register_secret("ab")
        assert redact("a normal sentence about abc") == "a normal sentence about abc"

    def test_formatter_masks_arguments_and_tracebacks(self) -> None:
        register_secret("tok-9876543210")
        formatter = RedactingFormatter("%(message)s")
        try:
            raise RuntimeError("boom tok-9876543210")
        except RuntimeError:
            import sys

            record = logging.LogRecord(
                "t", logging.ERROR, __file__, 1, "token is %s", ("tok-9876543210",), sys.exc_info()
            )
        out = formatter.format(record)
        assert "tok-9876543210" not in out and "***" in out


class _Ping(Event):
    wire_type = "test.ping"
    n: int = 0


class _Pong(Event):
    wire_type = "test.pong"


class TestEvents:
    def test_registry_and_wire_shape(self) -> None:
        assert EVENT_REGISTRY["test.ping"] is _Ping
        wire = _Ping(n=3, account_id="ACC1").to_wire()
        assert wire["type"] == "test.ping" and wire["accountId"] == "ACC1"
        assert wire["payload"] == {"n": 3}
        assert wire["occurredAt"].endswith("Z")

    def test_duplicate_wire_type_is_refused(self) -> None:
        with pytest.raises(TypeError):

            class _Dup(Event):
                wire_type = "test.ping"

    async def test_dispatch_by_type_and_all(self) -> None:
        dispatcher = EventDispatcher()
        seen_ping: list[Event] = []
        seen_all: list[Event] = []
        dispatcher.subscribe(_Ping, seen_ping.append)
        dispatcher.subscribe_all(seen_all.append)
        await dispatcher.publish(_Ping())
        await dispatcher.publish(_Pong())
        assert len(seen_ping) == 1 and len(seen_all) == 2

    async def test_handler_failure_is_isolated(self) -> None:
        dispatcher = EventDispatcher()
        later: list[Event] = []

        def boom(_: Event) -> None:
            raise RuntimeError("handler bug")

        async def async_boom(_: Event) -> None:
            raise RuntimeError("async handler bug")

        dispatcher.subscribe_all(boom)
        dispatcher.subscribe_all(async_boom)
        dispatcher.subscribe_all(later.append)
        await dispatcher.publish(_Pong())
        assert len(later) == 1 and dispatcher.handler_errors == 2


class TestSettings:
    def test_safe_defaults(self) -> None:
        s = Settings(_env_file=None)
        assert s.trading_mode is TradingMode.OBSERVE  # nothing is ever sent by default
        assert s.api_host == "127.0.0.1" and s.ea_link_host == "127.0.0.1"
        assert s.credential_store == "none"  # ADR 0013: nothing stored unless the user opts in
        assert s.database_url is None  # no password in the code

    def test_secrets_are_masked_and_registered(self) -> None:
        s = Settings(
            _env_file=None, database_url=SecretStr("postgresql://u:pw-1234@h/db"), fred_api_key=SecretStr("fredkey-1")
        )
        assert "pw-1234" not in repr(s) and "fredkey-1" not in repr(s)
        s.register_secrets()
        assert "pw-1234" not in redact("connect postgresql://u:pw-1234@h/db")

    def test_env_aliases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TRADINGOS_COCKPIT_TOKEN", "cockpit-tok")
        monkeypatch.setenv("TRADING_MODE", "PAPER")
        s = Settings(_env_file=None)
        assert s.trading_os_cockpit_token is not None and s.trading_os_cockpit_token.get_secret_value() == "cockpit-tok"
        assert s.trading_mode is TradingMode.PAPER

    def test_origins_are_split_and_trimmed(self) -> None:
        s = Settings(_env_file=None, allowed_origins=" http://a:1 , http://b:2 ,")
        assert s.origins == ["http://a:1", "http://b:2"]
