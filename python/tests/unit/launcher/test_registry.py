"""The process registry (ADR 0038, § 3): the launcher's only memory of what it started. It must survive a crash, never be trusted when it
is unreadable, never hold a secret, and never outlive the process it describes — a recorded pid counts only if a live process with that
pid has the very creation time that was recorded (Windows reuses pids)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tests.unit.launcher.support import T0, proc
from trading_os.launcher.model import Component, OwnedProcess
from trading_os.launcher.registry import ProcessRegistry, verify_owned
from trading_os.shared.logging.redaction import clear_secrets, register_secret
from trading_os.shared.time import ManualClock


def owned(component: Component = Component.CORE, pid: int = 4242, **changes: object) -> OwnedProcess:
    base: dict[str, object] = {
        "component": component,
        "pid": pid,
        "created_at": T0,
        "command_line": "python -m trading_os serve",
        "started_at": T0 + timedelta(seconds=1),
        "working_directory": r"C:\repo\04_code\python",
        "log_path": r"C:\repo\04_code\var\launcher\logs\core.log",
        "correlation_id": "c0ffee",
    }
    base.update(changes)
    return OwnedProcess(**base)  # type: ignore[arg-type]


@pytest.fixture
def registry(tmp_path: Path) -> ProcessRegistry:
    return ProcessRegistry(tmp_path / "var" / "launcher" / "state.json", ManualClock(T0))


class TestReadingAndWriting:
    def test_a_missing_file_is_an_empty_registry_without_a_problem(self, registry: ProcessRegistry) -> None:
        snapshot = registry.load()
        assert snapshot.owned == ()
        assert snapshot.problem is None

    def test_reading_never_creates_anything(self, registry: ProcessRegistry, tmp_path: Path) -> None:
        registry.load()
        assert not (tmp_path / "var").exists()

    def test_what_is_recorded_is_read_back(self, registry: ProcessRegistry) -> None:
        registry.record(owned())
        assert registry.load().owned == (owned(),)

    def test_recording_a_component_again_replaces_its_entry(self, registry: ProcessRegistry) -> None:
        registry.record(owned(pid=1))
        registry.record(owned(pid=2))
        assert [item.pid for item in registry.load().owned] == [2]

    def test_two_components_are_kept_side_by_side(self, registry: ProcessRegistry) -> None:
        registry.record(owned(Component.CORE, 1))
        registry.record(owned(Component.COCKPIT, 2))
        assert {item.component: item.pid for item in registry.load().owned} == {Component.CORE: 1, Component.COCKPIT: 2}

    def test_forgetting_removes_one_component_only(self, registry: ProcessRegistry) -> None:
        registry.record(owned(Component.CORE, 1))
        registry.record(owned(Component.COCKPIT, 2))
        registry.forget(Component.CORE)
        assert [item.component for item in registry.load().owned] == [Component.COCKPIT]

    def test_the_write_is_atomic_no_temporary_file_is_left(self, registry: ProcessRegistry, tmp_path: Path) -> None:
        registry.record(owned())
        names = sorted(path.name for path in (tmp_path / "var" / "launcher").iterdir())
        assert names == ["state.json"]

    def test_the_file_is_plain_json_with_a_version(self, registry: ProcessRegistry, tmp_path: Path) -> None:
        registry.record(owned())
        document = json.loads((tmp_path / "var" / "launcher" / "state.json").read_text(encoding="utf-8"))
        assert document["version"] == 1
        assert document["owned"][0]["pid"] == 4242


class TestAnUnreadableRegistryOwnsNothing:
    def write(self, tmp_path: Path, text: str) -> ProcessRegistry:
        path = tmp_path / "state.json"
        path.write_text(text, encoding="utf-8")
        return ProcessRegistry(path, ManualClock(T0))

    @pytest.mark.parametrize(
        "text",
        ["{ not json", "[]", '{"version": 2, "owned": []}', '{"version": 1, "owned": [{"pid": "x"}]}', ""],
    )
    def test_it_reports_a_problem_and_returns_no_entries(self, tmp_path: Path, text: str) -> None:
        snapshot = self.write(tmp_path, text).load()
        assert snapshot.owned == ()
        assert snapshot.problem

    def test_recording_keeps_the_unreadable_file_aside_as_evidence(self, tmp_path: Path) -> None:
        registry = self.write(tmp_path, "{ not json")
        registry.record(owned())
        assert registry.load().owned == (owned(),)
        aside = [path for path in tmp_path.iterdir() if "corrupt" in path.name]
        assert len(aside) == 1
        assert aside[0].read_text(encoding="utf-8") == "{ not json"


class TestNoSecretIsKept:
    def test_a_registered_secret_in_a_command_line_is_masked_before_it_is_written(
        self, registry: ProcessRegistry, tmp_path: Path
    ) -> None:
        clear_secrets()
        register_secret("s3cr3t-value-123")
        try:
            registry.record(owned(command_line="python serve --token s3cr3t-value-123"))
        finally:
            clear_secrets()
        text = (tmp_path / "var" / "launcher" / "state.json").read_text(encoding="utf-8")
        assert "s3cr3t-value-123" not in text


class TestOnlyLiveProcessesWithTheSameCreationTimeCount:
    def test_a_live_process_with_the_recorded_creation_time_is_verified(self) -> None:
        entry = owned(pid=10)
        assert verify_owned([entry], [proc(10, created_at=T0)]) == (entry,)

    def test_a_difference_under_a_second_is_the_same_process(self) -> None:
        entry = owned(pid=10)
        assert verify_owned([entry], [proc(10, created_at=T0 + timedelta(milliseconds=400))]) == (entry,)

    def test_a_recycled_pid_is_not_verified(self) -> None:
        assert verify_owned([owned(pid=10)], [proc(10, created_at=T0 + timedelta(hours=2))]) == ()

    def test_a_dead_process_is_not_verified(self) -> None:
        assert verify_owned([owned(pid=10)], [proc(11)]) == ()

    def test_a_live_process_whose_creation_time_is_unknown_cannot_be_verified(self) -> None:
        """Fail closed: when the identity cannot be proved, the process is not ours."""
        assert verify_owned([owned(pid=10)], [proc(10, created_at=None)]) == ()
