"""``python -m trading_os launcher mt5 detect | list | plan | register`` (ADR 0039, I3).

``detect``, ``list`` and ``plan`` are read-only. ``register`` writes **one** thing — the launcher's own ``var/launcher/terminals.json`` (and an event)
— and never a byte inside a MetaTrader folder. Exit codes follow the launcher's: 0 fine · 1 refused or failed · 2 the machine could not be read.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.launcher.mt5.support import (
    DATA,
    DATA_ID,
    EXE,
    INSTALL,
    FakeMt5Files,
    FakePrograms,
    add_data_folder,
    add_install,
    clock,
    config,
    standard_machine,
)
from tests.unit.launcher.support import FakeProcessTable, make_config, proc
from trading_os.cli.main import main
from trading_os.launcher.events import EventLog
from trading_os.launcher.mt5 import cli as mt5_cli
from trading_os.launcher.mt5.discovery import Mt5Discovery
from trading_os.launcher.mt5.ports import ProgramEntry
from trading_os.launcher.mt5.terminals import TerminalRegistry
from trading_os.launcher.ports import ProbeError

FULL = [
    "--account-id", "exness-486046157",
    "--expected-login", "486046157",
    "--symbol", "XAUUSDm",
    "--period", "M5",
    "--magic", "486046",
    "--allowed-symbols", "XAUUSDm,EURUSDm",
    "--provider", "EXNESS",
    "--product", "EXNESS_STANDARD",
]  # fmt: skip


@pytest.fixture
def machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    """The machine is replaced by fakes; the launcher's own state lives in ``tmp_path``, so any stray write is visible."""
    launcher_config = make_config(tmp_path / "repo" / "04_code")
    world = SimpleNamespace(files=None, programs=None, table=None, config=launcher_config, holder_pid=100)

    def set_up(files=None, programs=None, table=None) -> SimpleNamespace:  # type: ignore[no-untyped-def]
        default_files, default_programs, default_table = standard_machine()
        world.files = files or default_files
        world.programs = programs or default_programs
        world.table = table or default_table
        if hasattr(world.table, "_processes"):
            world.table._processes.append(proc(100))
        return world

    set_up()
    monkeypatch.setattr(mt5_cli, "default_config", lambda: launcher_config)
    monkeypatch.setattr(mt5_cli, "default_mt5_config", config)
    monkeypatch.setattr(
        mt5_cli,
        "make_discovery",
        lambda cfg: Mt5Discovery(
            config(), files=world.files, programs=world.programs, processes=world.table, clock=clock()
        ),
    )
    monkeypatch.setattr(mt5_cli, "make_files", lambda: world.files)
    monkeypatch.setattr(
        mt5_cli,
        "make_registry",
        lambda cfg: TerminalRegistry(cfg.terminals_path, clock(), world.table, pid=world.holder_pid),
    )
    monkeypatch.setattr(mt5_cli, "make_events", lambda cfg: EventLog(cfg.events_dir, clock()))
    world.set_up = set_up
    return world


def written(tmp_path: Path) -> list[str]:
    return sorted(str(p.relative_to(tmp_path)).replace("\\", "/") for p in tmp_path.rglob("*") if p.is_file())


class TestDetect:
    def test_it_lists_the_installation_its_version_its_data_folder_and_the_running_terminal(
        self, machine, capsys
    ) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "detect"]) == 0
        out = capsys.readouterr().out
        assert INSTALL in out and "5.0.0.6230" in out
        assert DATA_ID in out
        assert "en cours (pid 1872)" in out
        assert "lecture seule" in out

    def test_it_never_prints_what_a_terminal_was_started_with(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        line = f'"{EXE}" /login:123456 /password:hunter2 /server:Broker'
        machine.set_up(table=FakeProcessTable([proc(77, name="terminal64.exe", command_line=line, executable=EXE)]))
        assert main(["launcher", "mt5", "detect"]) == 0
        out = capsys.readouterr().out
        assert "hunter2" not in out and "123456" not in out and "/login" not in out

    def test_a_machine_without_metatrader_is_not_an_error(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        machine.set_up(FakeMt5Files(), FakePrograms(), FakeProcessTable())
        assert main(["launcher", "mt5", "detect"]) == 0
        assert "aucune installation de metatrader 5" in capsys.readouterr().out.lower()

    def test_json_is_parseable_and_camel_cased(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "detect", "--json"]) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["installations"][0]["dataFolders"][0]["terminalId"] == DATA_ID

    def test_an_unreadable_machine_exits_two_and_says_why(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        class Broken:
            def processes(self):  # type: ignore[no-untyped-def]
                raise ProbeError("PowerShell ne répond pas")

            def listeners(self, ports):  # type: ignore[no-untyped-def]
                return []

        machine.set_up(table=Broken())
        assert main(["launcher", "mt5", "detect"]) == 2
        assert "PowerShell ne répond pas" in capsys.readouterr().err

    def test_it_writes_nothing(self, machine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        main(["launcher", "mt5", "detect"])
        main(["launcher", "mt5", "detect", "--json"])
        assert written(tmp_path) == []


class TestList:
    def test_an_empty_registry_says_so(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "list"]) == 0
        assert "aucun terminal enregistré" in capsys.readouterr().out.lower()

    def test_a_registered_terminal_is_listed_with_what_it_declares_and_what_it_lacks(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        main(["launcher", "mt5", "register", "--terminal", DATA_ID, "--label", "exness-demo-01", "--magic", "486046"])
        capsys.readouterr()
        assert main(["launcher", "mt5", "list"]) == 0
        out = capsys.readouterr().out
        assert "exness-demo-01" in out and DATA_ID in out
        assert "486046" in out
        assert "manque :" in out

    def test_it_writes_nothing(self, machine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        main(["launcher", "mt5", "list"])
        assert written(tmp_path) == []


class TestPlan:
    def test_it_proposes_the_registration_of_what_it_found(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "plan"]) == 0
        out = capsys.readouterr().out
        assert f"launcher mt5 register --terminal {DATA_ID}" in out
        assert "n'en lance aucune" in out

    def test_json_is_parseable(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "plan", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["terminals"][0]["status"] == "UNREGISTERED"

    def test_an_unreadable_machine_exits_two(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        class Broken:
            def processes(self):  # type: ignore[no-untyped-def]
                raise ProbeError("illisible")

            def listeners(self, ports):  # type: ignore[no-untyped-def]
                return []

        machine.set_up(table=Broken())
        assert main(["launcher", "mt5", "plan"]) == 2

    def test_it_writes_nothing(self, machine, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        main(["launcher", "mt5", "plan"])
        assert written(tmp_path) == []


class TestRegisterADiscoveredTerminal:
    def test_a_complete_registration_writes_only_the_registry_and_an_event(
        self, machine, tmp_path: Path, capsys
    ) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "register", "--terminal", DATA_ID, "--label", "exness-demo-01", *FULL]) == 0
        out = capsys.readouterr().out
        assert "enregistré" in out
        assert "rien n'a été écrit dans MetaTrader 5" in out
        files = written(tmp_path)
        assert "repo/04_code/var/launcher/terminals.json" in files
        assert all(name.startswith("repo/04_code/var/launcher/") for name in files), files
        document = json.loads((machine.config.terminals_path).read_text(encoding="utf-8"))
        stored = document["terminals"][0]
        assert stored["terminalId"] == DATA_ID
        assert stored["installPath"] == INSTALL and stored["dataPath"] == DATA
        assert stored["source"] == "DISCOVERED"
        assert stored["declared"]["magic"] == 486046

    def test_an_event_names_the_terminal_without_any_declared_value(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        main(["launcher", "mt5", "register", "--terminal", DATA_ID, *FULL])
        (event,) = EventLog(machine.config.events_dir, clock()).read()
        assert event.type.value == "MT5_TERMINAL_REGISTERED"
        assert event.instance_id == DATA_ID
        assert "486046157" not in event.diagnostic  # a login is not copied into the events

    def test_a_registration_with_nothing_declared_lists_what_remains_to_declare(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "register", "--terminal", DATA_ID]) == 0
        out = capsys.readouterr().out
        assert "manque :" in out
        assert "login attendu" in out

    def test_an_unknown_terminal_is_refused_and_nothing_is_written(self, machine, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "register", "--terminal", "NOPE"]) == 1
        assert "inconnu" in capsys.readouterr().err
        assert written(tmp_path) == []

    def test_an_invalid_declaration_is_refused_and_named(self, machine, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "register", "--terminal", DATA_ID, "--magic", "0"]) == 1
        assert "numéro magique" in capsys.readouterr().err
        assert written(tmp_path) == []

    def test_the_chart_needs_both_a_symbol_and_a_period(self, machine, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        assert main(["launcher", "mt5", "register", "--terminal", DATA_ID, "--symbol", "XAUUSDm"]) == 1
        assert "symbole et une période" in capsys.readouterr().err
        assert written(tmp_path) == []

    def test_registering_again_updates_only_what_is_given(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        main(["launcher", "mt5", "register", "--terminal", DATA_ID, *FULL])
        capsys.readouterr()
        assert main(["launcher", "mt5", "register", "--terminal", DATA_ID, "--magic", "486047"]) == 0
        assert "mis à jour" in capsys.readouterr().out
        stored = json.loads(machine.config.terminals_path.read_text(encoding="utf-8"))["terminals"][0]
        assert stored["declared"]["magic"] == 486047
        assert stored["declared"]["expectedLogin"] == "486046157"  # untouched

    def test_two_terminals_cannot_share_a_magic_number(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        add_install(machine.files, r"D:\Brokers\FTMO MT5")
        add_data_folder(machine.files, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", origin=r"D:\Brokers\FTMO MT5")
        machine.programs = FakePrograms(
            [*machine.programs.programs(), ProgramEntry("MetaTrader 5 FTMO", (r"D:\Brokers\FTMO MT5",))]
        )
        main(["launcher", "mt5", "register", "--terminal", DATA_ID, "--magic", "486046"])
        capsys.readouterr()
        assert (
            main(["launcher", "mt5", "register", "--terminal", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "--magic", "486046"])
            == 1
        )
        err = capsys.readouterr().err
        assert "numéro magique" in err and DATA_ID in err

    def test_another_launcher_holding_the_registry_refuses_the_write(self, machine, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        lock = machine.config.terminals_path.with_name("terminals.json.lock")
        lock.parent.mkdir(parents=True)
        machine.table._processes.append(proc(555))
        lock.write_text(json.dumps({"pid": 555, "createdAt": "2026-11-06T15:30:00Z"}), encoding="utf-8")
        assert main(["launcher", "mt5", "register", "--terminal", DATA_ID]) == 1
        assert "555" in capsys.readouterr().err
        assert not machine.config.terminals_path.exists()


class TestRegisterByHand:
    """When detection fails (a terminal in a place nothing points to), a terminal is registered by hand — and checked as strictly."""

    def hand_made(self, machine):  # type: ignore[no-untyped-def]
        files, programs, table = FakeMt5Files(), FakePrograms(), FakeProcessTable()
        add_install(files, r"E:\Brokers\Real MT5")
        data = add_data_folder(files, "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", origin=r"E:\Brokers\Real MT5")
        return machine.set_up(files, programs, table), data

    def test_a_terminal_in_an_unknown_place_is_registered_when_the_files_agree(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        world, data = self.hand_made(machine)
        args = ["launcher", "mt5", "register", "--install-path", r"E:\Brokers\Real MT5", "--data-path", data]
        assert main([*args, "--label", "real-01"]) == 0
        stored = json.loads(world.config.terminals_path.read_text(encoding="utf-8"))["terminals"][0]
        assert stored["terminalId"] == "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
        assert stored["source"] == "MANUAL"

    def test_a_folder_without_the_executable_is_refused(self, machine, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        _, data = self.hand_made(machine)
        assert main(["launcher", "mt5", "register", "--install-path", r"E:\Nowhere", "--data-path", data]) == 1
        assert "terminal64.exe" in capsys.readouterr().err
        assert written(tmp_path) == []

    def test_a_data_folder_that_the_terminal_does_not_attribute_to_that_installation_is_refused(
        self, machine, capsys
    ) -> None:  # type: ignore[no-untyped-def]
        world, data = self.hand_made(machine)
        add_install(world.files, r"E:\Other MT5")
        assert main(["launcher", "mt5", "register", "--install-path", r"E:\Other MT5", "--data-path", data]) == 1
        err = capsys.readouterr().err
        assert "identité" in err and "origin" in err

    def test_an_installation_without_a_data_path_is_refused_unless_it_is_portable(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        self.hand_made(machine)
        assert main(["launcher", "mt5", "register", "--install-path", r"E:\Brokers\Real MT5"]) == 1
        assert "dossier de données" in capsys.readouterr().err

    def test_a_portable_terminal_needs_its_mql5_folder(self, machine, capsys) -> None:  # type: ignore[no-untyped-def]
        world, _ = self.hand_made(machine)
        assert main(["launcher", "mt5", "register", "--install-path", r"E:\Brokers\Real MT5", "--portable"]) == 1
        assert "MQL5" in capsys.readouterr().err
        world.files.add_dir(r"E:\Brokers\Real MT5\MQL5")
        assert main(["launcher", "mt5", "register", "--install-path", r"E:\Brokers\Real MT5", "--portable"]) == 0
        stored = json.loads(world.config.terminals_path.read_text(encoding="utf-8"))["terminals"][0]
        assert stored["portable"] is True
        assert stored["terminalId"].startswith("portable-")

    def test_a_discovered_id_and_a_hand_made_path_cannot_be_given_together(self, machine) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(SystemExit) as stopped:
            main(["launcher", "mt5", "register", "--terminal", DATA_ID, "--install-path", INSTALL])
        assert stopped.value.code == 2

    def test_one_of_them_is_required(self, machine) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(SystemExit) as stopped:
            main(["launcher", "mt5", "register"])
        assert stopped.value.code == 2


def test_the_mt5_command_needs_a_subcommand() -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["launcher", "mt5"])
    assert stopped.value.code == 2
