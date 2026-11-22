"""One launcher at a time (ADR 0038, § 4): two concurrent runs must not both start the application. The lock is a file holding the owner's pid
and creation time; a stale one (the owner is gone, or its pid was recycled) is replaced, a live one refuses the second run."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from tests.unit.launcher.support import T0, FakeProcessTable, proc
from trading_os.launcher.lock import LauncherBusy, LauncherLock, LockInspection, LockState, inspect_lock
from trading_os.shared.time import ManualClock


def lock_at(tmp_path: Path, table: FakeProcessTable, pid: int) -> LauncherLock:
    return LauncherLock(tmp_path / "var" / "launcher.lock", table, ManualClock(T0), pid=pid)


def test_acquiring_writes_the_owner_and_releasing_removes_it(tmp_path: Path) -> None:
    table = FakeProcessTable([proc(100)])
    lock = lock_at(tmp_path, table, 100)
    with lock:
        document = json.loads((tmp_path / "var" / "launcher.lock").read_text(encoding="utf-8"))
        assert document["pid"] == 100
    assert not (tmp_path / "var" / "launcher.lock").exists()


def test_a_live_owner_refuses_a_second_run(tmp_path: Path) -> None:
    table = FakeProcessTable([proc(100), proc(200)])
    first = lock_at(tmp_path, table, 100)
    with first, pytest.raises(LauncherBusy) as busy, lock_at(tmp_path, table, 200):
        pass
    assert "100" in str(busy.value)
    assert (tmp_path / "var" / "launcher.lock").exists() is False  # released by the first on exit


def test_the_second_run_does_not_remove_the_first_ones_lock(tmp_path: Path) -> None:
    table = FakeProcessTable([proc(100), proc(200)])
    with lock_at(tmp_path, table, 100):
        with pytest.raises(LauncherBusy), lock_at(tmp_path, table, 200):
            pass
        assert (tmp_path / "var" / "launcher.lock").exists()


def test_a_lock_whose_owner_is_gone_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "var" / "launcher.lock"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": 999, "createdAt": "2026-11-06T15:00:00Z"}), encoding="utf-8")
    with lock_at(tmp_path, FakeProcessTable([proc(100)]), 100):
        assert json.loads(path.read_text(encoding="utf-8"))["pid"] == 100


def test_a_recycled_pid_does_not_keep_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "var" / "launcher.lock"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"pid": 100, "createdAt": "2026-11-06T09:00:00Z"}), encoding="utf-8")
    table = FakeProcessTable([proc(100, created_at=T0 + timedelta(hours=1)), proc(200)])
    with lock_at(tmp_path, table, 200):
        assert json.loads(path.read_text(encoding="utf-8"))["pid"] == 200


def test_an_unreadable_lock_is_replaced_not_obeyed(tmp_path: Path) -> None:
    path = tmp_path / "var" / "launcher.lock"
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    with lock_at(tmp_path, FakeProcessTable([proc(100)]), 100):
        assert json.loads(path.read_text(encoding="utf-8"))["pid"] == 100


class TestInspection:
    """``launcher doctor`` looks at the lock without ever taking, replacing or removing it."""

    def write(self, tmp_path: Path, pid: int, created: str) -> Path:
        path = tmp_path / "var" / "launcher.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": pid, "createdAt": created}), encoding="utf-8")
        return path

    def test_no_file_is_a_free_lock_and_the_process_table_is_not_even_read(self, tmp_path: Path) -> None:
        class Forbidden:
            def processes(self):  # type: ignore[no-untyped-def]
                raise AssertionError("the process table must not be read when there is no lock file")

            def listeners(self, ports):  # type: ignore[no-untyped-def]
                raise AssertionError("not needed")

        assert inspect_lock(tmp_path / "var" / "launcher.lock", Forbidden()) == LockInspection(state=LockState.FREE)

    def test_a_live_owner_is_held_and_named(self, tmp_path: Path) -> None:
        path = self.write(tmp_path, 100, "2026-11-06T15:30:00Z")
        inspection = inspect_lock(path, FakeProcessTable([proc(100)]))
        assert inspection.state is LockState.HELD
        assert inspection.pid == 100

    @pytest.mark.parametrize("created", ["2026-11-06T09:00:00Z"])
    def test_a_recycled_pid_is_stale(self, tmp_path: Path, created: str) -> None:
        path = self.write(tmp_path, 100, created)
        assert inspect_lock(path, FakeProcessTable([proc(100)])).state is LockState.STALE

    def test_an_owner_that_is_gone_is_stale(self, tmp_path: Path) -> None:
        path = self.write(tmp_path, 999, "2026-11-06T15:30:00Z")
        inspection = inspect_lock(path, FakeProcessTable([proc(100)]))
        assert inspection.state is LockState.STALE
        assert inspection.pid == 999

    def test_an_unreadable_file_is_stale_without_a_pid(self, tmp_path: Path) -> None:
        path = tmp_path / "var" / "launcher.lock"
        path.parent.mkdir(parents=True)
        path.write_text("{ not json", encoding="utf-8")
        inspection = inspect_lock(path, FakeProcessTable([proc(100)]))
        assert inspection.state is LockState.STALE
        assert inspection.pid is None

    def test_looking_never_changes_the_file(self, tmp_path: Path) -> None:
        for pid, table in ((100, [proc(100)]), (999, [proc(100)])):
            path = self.write(tmp_path, pid, "2026-11-06T15:30:00Z")
            before = path.read_bytes()
            inspect_lock(path, FakeProcessTable(table))
            assert path.read_bytes() == before
