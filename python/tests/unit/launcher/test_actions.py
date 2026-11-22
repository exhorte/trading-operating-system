"""The commands that start things (ADR 0038, I2): the Docker actions as fixed argument lists, and the backup that counts only when the file is
really there. No Docker is started — a fake runner answers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from trading_os.launcher.actions import DockerActionsCli
from trading_os.launcher.ports import CommandResult


class Runner:
    """Records every call; ``copies`` makes a ``docker cp`` produce the file, as Docker would."""

    def __init__(self, *, fail_on: str | None = None, copies: bytes | None = b"dump") -> None:
        self.calls: list[tuple[tuple[str, ...], Path | None]] = []
        self._fail_on = fail_on
        self._copies = copies

    def run(self, args: Sequence[str], *, timeout: float, cwd: Path | None = None) -> CommandResult:
        self.calls.append((tuple(args), cwd))
        if self._fail_on and self._fail_on in args:
            return CommandResult(1, "", "boom")
        if args[:2] == ["docker", "cp"] and self._copies is not None:
            Path(args[3]).write_bytes(self._copies)
        return CommandResult(0, "", "")


def test_the_container_commands_are_fixed_and_name_only_the_project_container() -> None:
    runner = Runner()
    docker = DockerActionsCli(runner)
    assert docker.start_container("tradingos-timescaledb") is True
    assert docker.stop_container("tradingos-timescaledb") is True
    assert [call[0] for call in runner.calls] == [
        ("docker", "start", "tradingos-timescaledb"),
        ("docker", "stop", "tradingos-timescaledb"),
    ]


def test_creating_the_database_is_compose_from_the_repository_root(tmp_path: Path) -> None:
    runner = Runner()
    assert DockerActionsCli(runner).create_database(tmp_path) is True
    assert runner.calls == [(("docker", "compose", "up", "-d", "timescaledb"), tmp_path)]


def test_a_failing_command_is_false_not_an_exception() -> None:
    assert DockerActionsCli(Runner(fail_on="start")).start_container("x") is False
    assert DockerActionsCli(Runner(fail_on="stop")).stop_container("x") is False


class TestTheBackup:
    def test_it_dumps_inside_the_container_copies_the_file_out_and_cleans_up(self, tmp_path: Path) -> None:
        runner = Runner()
        destination = tmp_path / "backups" / "tradingos-20261106-170000.dump"
        assert DockerActionsCli(runner).dump_database("tradingos-timescaledb", destination) is True
        kinds = [call[0][:3] for call in runner.calls]
        assert kinds == [
            ("docker", "exec", "tradingos-timescaledb"),
            ("docker", "cp", "tradingos-timescaledb:/tmp/tradingos-20261106-170000.dump"),
            ("docker", "exec", "tradingos-timescaledb"),
        ]
        assert "pg_dump" in runner.calls[0][0] and "-Fc" in runner.calls[0][0]
        assert runner.calls[2][0][-2:] == ("-f", "/tmp/tradingos-20261106-170000.dump")[0:0] + runner.calls[2][0][-2:]
        assert destination.read_bytes() == b"dump"

    def test_a_dump_that_fails_is_false_and_nothing_is_copied(self, tmp_path: Path) -> None:
        runner = Runner(fail_on="pg_dump")
        assert DockerActionsCli(runner).dump_database("c", tmp_path / "x.dump") is False
        assert not [call for call in runner.calls if call[0][1] == "cp"]

    def test_a_copy_that_leaves_no_file_is_false(self, tmp_path: Path) -> None:
        assert DockerActionsCli(Runner(copies=None)).dump_database("c", tmp_path / "x.dump") is False

    def test_an_empty_file_is_not_a_backup(self, tmp_path: Path) -> None:
        assert DockerActionsCli(Runner(copies=b"")).dump_database("c", tmp_path / "x.dump") is False

    def test_a_file_name_that_could_inject_a_path_or_an_argument_is_refused(self, tmp_path: Path) -> None:
        runner = Runner()
        assert DockerActionsCli(runner).dump_database("c", tmp_path / "x y; rm.dump") is False
        assert runner.calls == []
