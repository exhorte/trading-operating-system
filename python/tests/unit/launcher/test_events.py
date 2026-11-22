"""The launcher's structured events (ADR 0038, § 12): one JSON line per event, UTC, with a correlation id, and never a secret — the launcher
runs before the database, so these live in files."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tests.unit.launcher.support import T0
from trading_os.launcher.events import EventLog, EventSeverity, EventType, new_correlation_id
from trading_os.shared.logging.redaction import clear_secrets, register_secret
from trading_os.shared.time import ManualClock


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(T0)


@pytest.fixture
def log(tmp_path: Path, clock: ManualClock) -> EventLog:
    return EventLog(tmp_path / "events", clock)


def lines(tmp_path: Path) -> list[dict[str, object]]:
    files = sorted((tmp_path / "events").glob("events-*.jsonl"))
    return [json.loads(line) for file in files for line in file.read_text(encoding="utf-8").splitlines()]


def test_the_event_vocabulary_names_the_steps_of_the_mission() -> None:
    names = {event.name for event in EventType}
    assert {
        "STARTUP_DATABASE_READY",
        "STARTUP_CORE_READY",
        "MT5_TERMINAL_DISCOVERED",
        "MT5_EA_DEPLOYED",
        "MT5_TERMINAL_STARTED",
        "MT5_EA_CONNECTED",
        "MT5_ACCOUNT_MISMATCH",
        "MT5_PROTOCOL_INCOMPATIBLE",
        "MT5_HEARTBEAT_TIMEOUT",
        "MT5_WEBREQUEST_NOT_ALLOWED",
        "EXECUTION_READINESS_BLOCKED",
        "LAUNCHER_PORT_FOREIGN_PROCESS",
    } <= names


def test_an_event_carries_the_fields_the_mission_asks_for(log: EventLog, tmp_path: Path) -> None:
    log.emit(
        EventType.STARTUP_CORE_READY,
        component="core",
        correlation_id="abc123",
        severity=EventSeverity.INFO,
        diagnostic="health ok",
        instance_id="D0E8",
        account_id="exness-demo",
    )
    (event,) = lines(tmp_path)
    assert event == {
        "occurredAt": "2026-11-06T15:30:00.000Z",
        "component": "core",
        "instanceId": "D0E8",
        "accountId": "exness-demo",
        "type": "STARTUP_CORE_READY",
        "severity": "INFO",
        "correlationId": "abc123",
        "diagnostic": "health ok",
    }


def test_optional_fields_are_present_and_null_when_unknown(log: EventLog, tmp_path: Path) -> None:
    log.emit(EventType.STARTUP_DATABASE_READY, component="database", correlation_id="x")
    (event,) = lines(tmp_path)
    assert event["instanceId"] is None
    assert event["accountId"] is None
    assert event["severity"] == "INFO"
    assert event["diagnostic"] == ""


def test_events_are_appended_one_line_each_and_never_rewritten(log: EventLog, tmp_path: Path) -> None:
    log.emit(EventType.STARTUP_DATABASE_READY, component="database", correlation_id="x")
    log.emit(EventType.STARTUP_CORE_READY, component="core", correlation_id="x")
    assert [event["type"] for event in lines(tmp_path)] == ["STARTUP_DATABASE_READY", "STARTUP_CORE_READY"]


def test_the_file_is_named_after_the_utc_day_and_rolls_over(log: EventLog, clock: ManualClock, tmp_path: Path) -> None:
    log.emit(EventType.STARTUP_DATABASE_READY, component="database", correlation_id="x")
    clock.advance(hours=10)
    log.emit(EventType.STARTUP_CORE_READY, component="core", correlation_id="x")
    assert sorted(path.name for path in (tmp_path / "events").iterdir()) == [
        "events-20261106.jsonl",
        "events-20261107.jsonl",
    ]


def test_a_secret_is_masked_in_the_diagnostic(log: EventLog, tmp_path: Path) -> None:
    clear_secrets()
    register_secret("agent-token-abcdef")
    try:
        log.emit(
            EventType.MT5_EA_DEPLOYED,
            component="mt5",
            correlation_id="x",
            diagnostic="wrote agent-token-abcdef to Files",
        )
    finally:
        clear_secrets()
    text = "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "events").iterdir())
    assert "agent-token-abcdef" not in text
    assert "***" in text


def test_a_token_shaped_value_is_masked_even_when_it_was_never_registered(log: EventLog, tmp_path: Path) -> None:
    log.emit(EventType.MT5_EA_DEPLOYED, component="mt5", correlation_id="x", diagnostic="token=zzz999yyy888")
    text = "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "events").iterdir())
    assert "zzz999yyy888" not in text


def test_reading_returns_the_last_events_in_order_and_skips_damaged_lines(
    log: EventLog, clock: ManualClock, tmp_path: Path
) -> None:
    for index in range(5):
        log.emit(EventType.STARTUP_CORE_READY, component="core", correlation_id=f"c{index}")
        clock.advance(seconds=1)
    day = next((tmp_path / "events").glob("events-*.jsonl"))
    with day.open("a", encoding="utf-8") as handle:
        handle.write("{ damaged line\n")
    events = log.read(limit=3)
    assert [event.correlation_id for event in events] == ["c2", "c3", "c4"]


def test_reading_a_directory_that_does_not_exist_gives_nothing_and_creates_nothing(
    clock: ManualClock, tmp_path: Path
) -> None:
    assert EventLog(tmp_path / "nothing-here", clock).read() == []
    assert not (tmp_path / "nothing-here").exists()


def test_correlation_ids_are_short_and_distinct() -> None:
    first, second = new_correlation_id(), new_correlation_id()
    assert first != second
    assert len(first) == 12
    assert all(character in "0123456789abcdef" for character in first)


def test_an_event_timestamp_is_utc_even_if_the_clock_is_not(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timezone

    clock = ManualClock(datetime(2026, 11, 6, 17, 0, tzinfo=timezone(timedelta(hours=2))))
    EventLog(tmp_path / "e", clock).emit(EventType.STARTUP_CORE_READY, component="core", correlation_id="x")
    (event,) = [
        json.loads(line) for path in (tmp_path / "e").iterdir() for line in path.read_text("utf-8").splitlines()
    ]
    assert event["occurredAt"] == "2026-11-06T15:00:00.000Z"
    assert datetime.fromisoformat(str(event["occurredAt"]).replace("Z", "+00:00")).tzinfo == UTC
