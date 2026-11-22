"""The core and the cockpit must outlive the window — or the assistant session — that started them (2026-11-14: both died when the session that had
launched them closed its Windows job). ``SubprocessSpawner`` asks to leave the job, and falls back to staying inside it when the job forbids it."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from trading_os.launcher.actions import SubprocessSpawner
from trading_os.launcher.ports import SpawnError

BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)

pytestmark = pytest.mark.skipif(not BREAKAWAY, reason="Windows only: jobs and their breakaway flag")


class FakeProcess:
    pid = 4242


def test_the_process_leaves_the_job_of_whoever_launched_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []

    def popen(*args: Any, creationflags: int = 0, **kwargs: Any) -> FakeProcess:
        seen.append(creationflags)
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", popen)
    assert SubprocessSpawner().spawn(["core"], cwd=tmp_path, log_path=tmp_path / "core.log") == 4242
    assert seen and seen[0] & BREAKAWAY and seen[0] & subprocess.CREATE_NEW_PROCESS_GROUP


def test_a_job_that_forbids_breaking_away_still_gets_the_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    def popen(*args: Any, creationflags: int = 0, **kwargs: Any) -> FakeProcess:
        seen.append(creationflags)
        if creationflags & BREAKAWAY:
            raise PermissionError(5, "Access is denied")
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", popen)
    assert SubprocessSpawner().spawn(["core"], cwd=tmp_path, log_path=tmp_path / "core.log") == 4242
    assert len(seen) == 2 and not seen[1] & BREAKAWAY


def test_a_program_that_does_not_exist_is_still_a_spawn_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def popen(*args: Any, **kwargs: Any) -> FakeProcess:
        raise FileNotFoundError(2, "not found")

    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(SpawnError):
        SubprocessSpawner().spawn(["nope"], cwd=tmp_path, log_path=tmp_path / "x.log")
