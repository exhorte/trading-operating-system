"""The read-only adapters (ADR 0038, § 2): PowerShell for processes and ports, the Docker CLI, HTTP. They are tested against **canned
output** and a fake command runner — no PowerShell, Docker or socket is started — and the one thing they must prove about their commands
is that they are fixed argument lists (no shell, nothing interpolated but integers), and that what they cannot read **fails closed**."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx
import pytest

from trading_os.launcher.adapters import (
    CommandResult,
    DockerCli,
    HttpxProbe,
    LocalEnvironment,
    SubprocessRunner,
    WindowsProcessTable,
)
from trading_os.launcher.model import Mt5WorkersFacts
from trading_os.launcher.ports import ProbeError


class ScriptedRunner:
    """Answers each call with the next canned result and keeps what it was asked."""

    def __init__(self, *results: CommandResult) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: Sequence[str], *, timeout: float, cwd: object = None) -> CommandResult:
        self.calls.append(tuple(args))
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]


def ok(stdout: str) -> CommandResult:
    return CommandResult(returncode=0, stdout=stdout, stderr="")


def failed(code: int = 1, stderr: str = "boom") -> CommandResult:
    return CommandResult(returncode=code, stdout="", stderr=stderr)


class TestProcessTable:
    SAMPLE = json.dumps(
        [
            {
                "pid": 1668,
                "parentPid": 16780,
                "name": "python.exe",
                "executable": r"C:\Python314\python.exe",
                "commandLine": r'"C:\repo\04_code\python\.venv\Scripts\python.exe" -m trading_os serve',
                "createdAt": "2026-11-06T15:30:29.6401810Z",
            },
            {"pid": 4, "parentPid": 0, "name": "System", "executable": None, "commandLine": None, "createdAt": None},
        ]
    )

    def test_processes_are_parsed_including_seven_digit_fractions_and_missing_fields(self) -> None:
        table = WindowsProcessTable(ScriptedRunner(ok(self.SAMPLE)))
        first, system = table.processes()
        assert (first.pid, first.parent_pid, first.name) == (1668, 16780, "python.exe")
        assert first.created_at == datetime(2026, 11, 6, 15, 30, 29, 640181, tzinfo=UTC)
        assert "trading_os serve" in first.command_line
        assert system.command_line == ""
        assert system.created_at is None
        assert system.executable is None

    def test_a_single_object_instead_of_a_list_is_accepted(self) -> None:
        one = json.dumps(
            {"pid": 7, "parentPid": 1, "name": "node.exe", "executable": None, "commandLine": "x", "createdAt": None}
        )
        assert [p.pid for p in WindowsProcessTable(ScriptedRunner(ok(one))).processes()] == [7]

    def test_listeners_are_parsed(self) -> None:
        sample = json.dumps(
            [{"address": "127.0.0.1", "port": 8000, "pid": 1668}, {"address": "::", "port": 3000, "pid": 7900}]
        )
        found = WindowsProcessTable(ScriptedRunner(ok(sample))).listeners([8000, 3000])
        assert [(item.address, item.port, item.pid) for item in found] == [
            ("127.0.0.1", 8000, 1668),
            ("::", 3000, 7900),
        ]

    def test_no_listener_is_an_empty_list_not_an_error(self) -> None:
        assert WindowsProcessTable(ScriptedRunner(ok("[]"))).listeners([8000]) == []
        assert WindowsProcessTable(ScriptedRunner(ok(""))).listeners([8000]) == []

    @pytest.mark.parametrize("result", [failed(), ok("not json"), ok('"a string"'), CommandResult(124, "", "timeout")])
    def test_what_cannot_be_read_raises_instead_of_pretending_nothing_runs(self, result: CommandResult) -> None:
        with pytest.raises(ProbeError):
            WindowsProcessTable(ScriptedRunner(result)).processes()

    def test_the_command_is_a_fixed_argument_list_with_no_shell(self) -> None:
        runner = ScriptedRunner(ok("[]"))
        WindowsProcessTable(runner).listeners([3000, 8000])
        (call,) = runner.calls
        assert call[0] == "powershell.exe"
        assert {"-NoProfile", "-NonInteractive"} <= set(call)
        assert "3000,8000" in call[-1].replace(" ", "")

    def test_ports_are_integers_only(self) -> None:
        with pytest.raises(TypeError):
            WindowsProcessTable(ScriptedRunner(ok("[]"))).listeners(["3000; calc"])  # type: ignore[list-item]

    def test_the_commands_only_read(self) -> None:
        runner = ScriptedRunner(ok("[]"))
        table = WindowsProcessTable(runner)
        table.processes()
        table.listeners([3000])
        script = " ".join(" ".join(call) for call in runner.calls)
        for verb in (
            "Stop-Process",
            "Remove-Item",
            "Set-",
            "New-Item",
            "Start-Process",
            "taskkill",
            "Invoke-Expression",
        ):
            assert verb not in script


class TestDocker:
    INSPECT = json.dumps(
        [
            {
                "Name": "/tradingos-timescaledb",
                "State": {"Status": "running", "Health": {"Status": "healthy"}},
                "NetworkSettings": {"Ports": {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5433"}]}},
            }
        ]
    )

    def test_the_daemon_answers_when_docker_info_succeeds(self) -> None:
        assert DockerCli(ScriptedRunner(ok("29.4.3"))).available() is True

    @pytest.mark.parametrize(
        "result", [failed(), CommandResult(124, "", "timeout"), CommandResult(127, "", "docker not found")]
    )
    def test_a_daemon_that_does_not_answer_is_unavailable(self, result: CommandResult) -> None:
        assert DockerCli(ScriptedRunner(result)).available() is False

    def test_a_daemon_that_misses_its_first_deadline_but_answers_the_second_time_is_available(self) -> None:
        runner = ScriptedRunner(CommandResult(124, "", "timeout"), ok("29.4.3"))
        assert DockerCli(runner).available() is True
        assert len(runner.calls) == 2

    def test_a_daemon_that_never_answers_is_asked_twice_and_then_unavailable(self) -> None:
        runner = ScriptedRunner(CommandResult(124, "", "timeout"))
        assert DockerCli(runner).available() is False
        assert len(runner.calls) == 2

    def test_docker_that_is_not_installed_is_asked_once(self) -> None:
        runner = ScriptedRunner(CommandResult(127, "", "docker not found"))
        assert DockerCli(runner).available() is False
        assert len(runner.calls) == 1

    def test_a_container_is_read_from_docker_inspect(self) -> None:
        info = DockerCli(ScriptedRunner(ok(self.INSPECT))).container("tradingos-timescaledb")
        assert info is not None
        assert (info.name, info.status, info.health, info.host_ports) == (
            "tradingos-timescaledb",
            "running",
            "healthy",
            (5433,),
        )

    def test_a_container_without_a_health_check_has_no_health(self) -> None:
        sample = json.dumps([{"Name": "/x", "State": {"Status": "exited"}, "NetworkSettings": {"Ports": {}}}])
        info = DockerCli(ScriptedRunner(ok(sample))).container("x")
        assert info is not None
        assert info.health is None
        assert info.host_ports == ()

    def test_an_unknown_container_is_none(self) -> None:
        assert DockerCli(ScriptedRunner(failed(1, "No such object"))).container("nope") is None

    def test_unreadable_inspect_output_is_an_error_not_an_absent_container(self) -> None:
        with pytest.raises(ProbeError):
            DockerCli(ScriptedRunner(ok("not json"))).container("x")

    def test_the_names_of_the_containers_publishing_a_port(self) -> None:
        assert DockerCli(ScriptedRunner(ok("tradingos-timescaledb\ndossier-db-1\n"))).port_holders(5433) == [
            "tradingos-timescaledb",
            "dossier-db-1",
        ]
        assert DockerCli(ScriptedRunner(ok(""))).port_holders(5433) == []

    def test_the_commands_are_read_only_and_fixed(self) -> None:
        runner = ScriptedRunner(ok(self.INSPECT))
        cli = DockerCli(runner)
        cli.available()
        cli.container("tradingos-timescaledb")
        cli.port_holders(5433)
        verbs = {call[1] for call in runner.calls}
        assert verbs <= {"info", "inspect", "ps"}
        assert all(call[0] == "docker" for call in runner.calls)


class TestHttp:
    HEALTH: ClassVar[dict[str, Any]] = {
        "status": "ok",
        "version": "0.2.0",
        "startedAt": "2026-11-06T15:30:39.395979Z",
        "database": {"up": True},
        "findings": [{"code": "x"}],
    }

    def probe(self, handler: httpx.MockTransport) -> HttpxProbe:
        return HttpxProbe(transport=handler)

    def test_the_core_health_is_parsed(self) -> None:
        probe = self.probe(httpx.MockTransport(lambda request: httpx.Response(200, json=self.HEALTH)))
        health = probe.core_health("http://127.0.0.1:8000/api/system/health")
        assert health is not None
        assert (health.status, health.version, health.database_up, health.findings) == ("ok", "0.2.0", True, 1)
        assert health.started_at == datetime(2026, 11, 6, 15, 30, 39, 395979, tzinfo=UTC)

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(500, json={}),
            httpx.Response(200, text="<html>"),
            httpx.Response(200, json=[1, 2]),
            httpx.Response(200, json={"status": "ok"}),
        ],
    )
    def test_anything_that_is_not_a_health_report_is_no_answer(self, response: httpx.Response) -> None:
        assert self.probe(httpx.MockTransport(lambda request: response)).core_health("http://127.0.0.1:8000/x") is None

    def test_the_agents_the_workers_and_the_mode_the_core_reports_are_parsed(self) -> None:
        body = {
            **self.HEALTH,
            "agentsConnected": 1,
            "mt5Workers": {"spawned": 15, "ended": 14, "alive": 1},
            "executionMode": "OFF",
        }
        probe = self.probe(httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
        health = probe.core_health("http://127.0.0.1:8000/x")
        assert health is not None
        assert health.agents_connected == 1
        assert health.mt5_workers == Mt5WorkersFacts(spawned=15, ended=14, alive=1)
        assert health.execution_mode == "OFF"

    def test_a_core_that_does_not_report_them_gives_none_not_zero(self) -> None:
        probe = self.probe(httpx.MockTransport(lambda request: httpx.Response(200, json=self.HEALTH)))
        health = probe.core_health("http://127.0.0.1:8000/x")
        assert health is not None
        assert (health.agents_connected, health.mt5_workers, health.execution_mode) == (None, None, None)

    @pytest.mark.parametrize(
        "extra",
        [
            {"agentsConnected": "one", "mt5Workers": {"spawned": "a", "ended": 1, "alive": 1}, "executionMode": 3},
            {"agentsConnected": True, "mt5Workers": [1, 2, 3], "executionMode": None},
            {"agentsConnected": -1, "mt5Workers": {"spawned": 1, "ended": 0}, "executionMode": ""},
        ],
    )
    def test_values_of_the_wrong_kind_are_dropped_and_never_break_the_health(self, extra: dict[str, Any]) -> None:
        probe = self.probe(httpx.MockTransport(lambda request: httpx.Response(200, json={**self.HEALTH, **extra})))
        health = probe.core_health("http://127.0.0.1:8000/x")
        assert health is not None
        assert health.status == "ok"
        assert (health.agents_connected, health.mt5_workers, health.execution_mode) == (None, None, None)

    def test_a_connection_error_is_no_answer(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        probe = self.probe(httpx.MockTransport(refuse))
        assert probe.core_health("http://127.0.0.1:8000/x") is None
        assert probe.http_status("http://127.0.0.1:3000/") is None

    def test_the_status_code_of_a_page_is_returned_without_following_redirects(self) -> None:
        probe = self.probe(httpx.MockTransport(lambda request: httpx.Response(307, headers={"location": "/x"})))
        assert probe.http_status("http://127.0.0.1:3000/") == 307

    def test_only_get_requests_are_made(self) -> None:
        seen: list[str] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request.method)
            return httpx.Response(200, json=self.HEALTH)

        probe = self.probe(httpx.MockTransport(record))
        probe.core_health("http://127.0.0.1:8000/x")
        probe.http_status("http://127.0.0.1:3000/")
        assert set(seen) == {"GET"}

    # A first request to ``next dev`` can take longer than the probe waits while it compiles (measured: 5 s on a loaded machine, then 1 s): a
    # transport error is worth one more try — a response, whatever its code, is an answer and is never asked again.

    def slow_then_fine(self, answer: httpx.Response) -> tuple[httpx.MockTransport, list[int]]:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                raise httpx.ReadTimeout("compiling…")
            return answer

        return httpx.MockTransport(handler), calls

    def test_a_page_that_times_out_once_and_then_answers_is_healthy(self) -> None:
        transport, calls = self.slow_then_fine(httpx.Response(200, text="ok"))
        assert self.probe(transport).http_status("http://127.0.0.1:3000/") == 200
        assert len(calls) == 2

    def test_the_core_health_gets_the_same_second_chance(self) -> None:
        transport, calls = self.slow_then_fine(httpx.Response(200, json=self.HEALTH))
        health = self.probe(transport).core_health("http://127.0.0.1:8000/api/system/health")
        assert health is not None and health.status == "ok"
        assert len(calls) == 2

    def test_two_failures_in_a_row_are_no_answer_and_only_two_requests_are_made(self) -> None:
        calls: list[int] = []

        def always_late(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            raise httpx.ConnectTimeout("no answer")

        probe = self.probe(httpx.MockTransport(always_late))
        assert probe.http_status("http://127.0.0.1:3000/") is None
        assert probe.core_health("http://127.0.0.1:8000/x") is None
        assert len(calls) == 4  # two probes, two tries each — never a loop

    @pytest.mark.parametrize("status", [404, 500, 503])
    def test_a_response_is_never_asked_again_whatever_its_code(self, status: int) -> None:
        calls: list[int] = []

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(status)

        assert self.probe(httpx.MockTransport(respond)).http_status("http://127.0.0.1:3000/") == status
        assert len(calls) == 1


class TestEnvironmentAndRunner:
    def test_path_exists_and_which(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        environment = LocalEnvironment()
        assert environment.path_exists(tmp_path) is True
        assert environment.path_exists(tmp_path / "missing") is False
        assert environment.which("definitely-not-a-real-tool-name") is None

    def test_the_real_runner_captures_output_and_never_uses_a_shell(self) -> None:
        result = SubprocessRunner().run([sys.executable, "-c", "print('hello')"], timeout=20)
        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_a_missing_executable_is_a_failed_result_not_an_exception(self) -> None:
        result = SubprocessRunner().run(["definitely-not-a-real-executable-name"], timeout=5)
        assert result.returncode != 0
