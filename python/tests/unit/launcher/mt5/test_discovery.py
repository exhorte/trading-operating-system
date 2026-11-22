"""Finding the MetaTrader 5 installations, their data folders and their instances (ADR 0038 § 6, I3): **read-only**, nothing assumed.

No location is taken for granted (a terminal can live anywhere), several terminals are listed and **never** auto-selected, a data folder is tied to
an installation only by what the terminal itself wrote (``origin.txt``), and the command line of a running terminal — which may carry a login or a
password — is never kept.
"""

from __future__ import annotations

import pytest

from tests.unit.launcher.mt5.support import (
    DATA,
    DATA_ID,
    DATA_ROOT,
    EA_TARGET,
    EXE,
    INSTALL,
    PROGRAM_FILES,
    FakeMt5Files,
    FakePrograms,
    add_data_folder,
    add_install,
    clock,
    config,
    file_entry,
    folder,
    junction,
    standard_machine,
)
from tests.unit.launcher.support import FakeProcessTable, proc
from trading_os.launcher.mt5.discovery import Mt5Discovery
from trading_os.launcher.mt5.model import DiscoveryResult, DiscoverySource, EaInstallKind
from trading_os.launcher.mt5.ports import ProgramEntry
from trading_os.launcher.ports import ProbeError


def discover(files=None, programs=None, table=None, extra=()):  # type: ignore[no-untyped-def]
    default_files, default_programs, default_table = standard_machine()
    return Mt5Discovery(
        config(),
        files=files or default_files,
        programs=programs or default_programs,
        processes=table or default_table,
        clock=clock(),
    ).discover(extra_install_paths=extra)


def nothing_installed() -> tuple[FakeMt5Files, FakePrograms, FakeProcessTable]:
    return FakeMt5Files(), FakePrograms(), FakeProcessTable()


class TestTheWorkstationAsAudited:
    def test_one_installation_with_its_version_found_three_ways(self) -> None:
        result = discover()
        (installation,) = result.installations
        assert installation.install_path == INSTALL
        assert installation.exe_path == EXE
        assert installation.version == "5.0.0.6230"
        assert set(installation.sources) == {
            DiscoverySource.REGISTRY,
            DiscoverySource.KNOWN_DIRECTORY,
            DiscoverySource.RUNNING_PROCESS,
        }

    def test_the_data_folder_is_tied_to_it_by_its_origin_and_named_by_its_folder(self) -> None:
        (installation,) = discover().installations
        (data,) = installation.data_folders
        assert data.terminal_id == DATA_ID
        assert data.path == DATA
        assert data.origin == INSTALL
        assert data.portable is False

    def test_common_and_community_have_no_origin_and_are_not_terminals(self) -> None:
        result = discover()
        assert [d.terminal_id for i in result.installations for d in i.data_folders] == [DATA_ID]
        assert result.unmatched_data_folders == ()

    def test_our_agent_is_found_as_a_junction_with_its_target_and_the_third_party_ea_is_only_named(self) -> None:
        (data,) = discover().installations[0].data_folders
        (agent,) = data.eas
        assert agent.kind is EaInstallKind.JUNCTION
        assert agent.name == "TradingOsAgent"
        assert agent.target == EA_TARGET
        assert data.third_party_experts == ("Ultimate_ICT_Gold_Scalper_v4.0.ex5",)

    def test_the_missing_presets_folder_and_the_present_link_file_are_reported_as_facts(self) -> None:
        (data,) = discover().installations[0].data_folders
        assert data.experts_present is True
        assert data.presets_present is False
        assert data.files_present is True
        assert data.link_file_present is True

    def test_the_running_terminal_is_reported_with_its_pid(self) -> None:
        (running,) = discover().installations[0].running
        assert running.pid == 1872
        assert running.portable is False
        assert running.config_file_given is False


class TestNothingIsAssumed:
    def test_a_machine_without_metatrader_gives_an_empty_result_not_an_error(self) -> None:
        result = discover(*nothing_installed())
        assert result.installations == ()
        assert result.rejected == ()

    def test_another_product_in_the_registry_is_ignored(self) -> None:
        files, _, table = nothing_installed()
        programs = FakePrograms([ProgramEntry(display_name="Docker Desktop", locations=(r"C:\Program Files\Docker",))])
        assert discover(files, programs, table).installations == ()

    def test_a_registry_location_without_the_executable_is_rejected_with_its_reason(self) -> None:
        files, _, table = nothing_installed()
        files.add_dir(r"D:\Old\MetaTrader 5")
        programs = FakePrograms([ProgramEntry(display_name="MetaTrader 5", locations=(r"D:\Old\MetaTrader 5",))])
        result = discover(files, programs, table)
        assert result.installations == ()
        (rejected,) = result.rejected
        assert rejected.path == r"D:\Old\MetaTrader 5"
        assert "terminal64.exe" in rejected.reason
        assert rejected.source is DiscoverySource.REGISTRY

    def test_an_installation_in_a_non_standard_place_is_found_through_its_running_process(self) -> None:
        files, programs, _ = nothing_installed()
        add_install(files, r"D:\Trading\FTMO MT5", "5.0.0.6100")
        exe = r"D:\Trading\FTMO MT5\terminal64.exe"
        table = FakeProcessTable([proc(4321, name="terminal64.exe", command_line=f'"{exe}" /portable', executable=exe)])
        (installation,) = discover(files, programs, table).installations
        assert installation.install_path == r"D:\Trading\FTMO MT5"
        assert installation.sources == (DiscoverySource.RUNNING_PROCESS,)
        assert installation.version == "5.0.0.6100"

    def test_a_declared_path_is_checked_like_any_other(self) -> None:
        files, programs, table = nothing_installed()
        add_install(files, r"E:\Brokers\Real MT5")
        (installation,) = discover(files, programs, table, extra=[r"E:\Brokers\Real MT5"]).installations
        assert installation.sources == (DiscoverySource.REGISTERED,)
        assert discover(files, programs, table, extra=[r"E:\Nowhere"]).rejected[0].source is DiscoverySource.REGISTERED

    def test_the_same_installation_written_two_ways_is_one_installation(self) -> None:
        files, programs, table = standard_machine()
        programs = FakePrograms([ProgramEntry(display_name="MetaTrader 5", locations=(INSTALL.lower() + "\\",))])
        assert len(discover(files, programs, table).installations) == 1

    def test_an_unreadable_version_is_none_not_an_error(self) -> None:
        files, programs, table = standard_machine()
        files.versions.clear()
        assert discover(files, programs, table).installations[0].version is None

    def test_an_unreadable_process_table_fails_closed(self) -> None:
        class Broken:
            def processes(self):  # type: ignore[no-untyped-def]
                raise ProbeError("la table des processus ne répond pas")

            def listeners(self, ports):  # type: ignore[no-untyped-def]
                return []

        files, programs, _ = standard_machine()
        with pytest.raises(ProbeError):
            discover(files, programs, Broken())


class TestSeveralTerminals:
    def machine(self):  # type: ignore[no-untyped-def]
        files, programs, table = standard_machine()
        add_install(files, r"D:\Brokers\FTMO MT5", "5.0.0.6200")
        add_data_folder(files, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", origin=r"D:\Brokers\FTMO MT5")
        files.add_dir(r"D:\Brokers", folder("FTMO MT5"))
        programs = FakePrograms(
            [
                ProgramEntry("MetaTrader 5", (INSTALL,)),
                ProgramEntry("MetaTrader 5 FTMO", (r"D:\Brokers\FTMO MT5",)),
            ]
        )
        return files, programs, table

    def test_each_installation_is_listed_in_a_stable_order(self) -> None:
        result = discover(*self.machine())
        assert [i.install_path for i in result.installations] == [INSTALL, r"D:\Brokers\FTMO MT5"]
        assert [d.terminal_id for i in result.installations for d in i.data_folders] == [
            DATA_ID,
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        ]

    def test_nothing_is_ever_selected_for_the_user(self) -> None:
        result = discover(*self.machine())
        for forbidden in ("selected", "default", "chosen", "current", "preferred"):
            assert not hasattr(result, forbidden)
            assert not any(hasattr(i, forbidden) for i in result.installations)

    def test_a_data_folder_whose_origin_is_an_installation_that_is_gone_is_reported_not_attached(self) -> None:
        files, programs, table = standard_machine()
        add_data_folder(files, "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", origin=r"X:\Uninstalled\MT5")
        result = discover(files, programs, table)
        assert len(result.installations[0].data_folders) == 1
        assert len(result.unmatched_data_folders) == 1
        assert "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB" in result.unmatched_data_folders[0]
        assert r"X:\Uninstalled\MT5" in result.unmatched_data_folders[0]


class TestAPortableTerminal:
    def machine(self):  # type: ignore[no-untyped-def]
        files, programs, _ = nothing_installed()
        install = r"D:\Portable\MT5"
        add_install(files, install)
        files.add_dir(install + r"\MQL5")
        files.add_dir(install + r"\MQL5\Experts")
        exe = install + r"\terminal64.exe"
        table = FakeProcessTable([proc(900, name="terminal64.exe", command_line=f'"{exe}" /portable', executable=exe)])
        return files, programs, table

    def test_a_terminal_running_with_portable_keeps_its_data_in_its_own_folder(self) -> None:
        (installation,) = discover(*self.machine()).installations
        (data,) = installation.data_folders
        assert data.portable is True
        assert data.path == r"D:\Portable\MT5"
        assert data.terminal_id.startswith("portable-")
        assert installation.running[0].portable is True

    def test_the_portable_identifier_is_stable_and_does_not_depend_on_letter_case(self) -> None:
        first = discover(*self.machine()).installations[0].data_folders[0].terminal_id
        second = discover(*self.machine()).installations[0].data_folders[0].terminal_id
        assert first == second
        assert len(first) == len("portable-") + 16


class TestWhatIsNeverKept:
    def test_the_command_line_of_a_running_terminal_is_never_stored(self) -> None:
        """MetaTrader accepts ``/login:`` and ``/password:`` on its command line: whatever a terminal was started with must not reach a report."""
        files, programs, _ = standard_machine()
        secret = "hunter2-do-not-keep"
        line = f'"{EXE}" /login:123456 /password:{secret} /server:Broker /config:C:\\x\\startup.ini'
        table = FakeProcessTable([proc(77, name="terminal64.exe", command_line=line, executable=EXE)])
        result = discover(files, programs, table)
        dumped = result.model_dump_json()
        assert secret not in dumped
        assert "123456" not in dumped
        assert "/login" not in dumped and "/password" not in dumped
        assert result.installations[0].running[0].config_file_given is True

    def test_only_the_origin_of_a_data_folder_is_ever_read_from_a_file(self) -> None:
        files, programs, table = standard_machine()
        discover(files, programs, table)
        assert {verb for verb, _ in files.asked} <= {
            "is_dir",
            "is_file",
            "list_directory",
            "read_origin",
            "file_version",
        }
        read_from = {path for verb, path in files.asked if verb == "read_origin"}
        assert all(path.startswith(DATA_ROOT) for path in read_from)


def test_the_result_is_a_plain_serialisable_model() -> None:
    result = discover()
    assert isinstance(result, DiscoveryResult)
    assert "installations" in result.model_dump(mode="json", by_alias=True)


def test_known_directories_are_only_looked_for_in_the_configured_roots() -> None:
    files, programs, table = nothing_installed()
    add_install(files, PROGRAM_FILES + r"\MetaTrader 5 EXNESS")
    files.add_dir(
        PROGRAM_FILES, folder("MetaTrader 5 EXNESS"), file_entry("MetaTrader readme.txt"), junction("MT5 link", r"C:\x")
    )
    (installation,) = discover(files, programs, table).installations
    assert installation.install_path == PROGRAM_FILES + r"\MetaTrader 5 EXNESS"
    assert installation.sources == (DiscoverySource.KNOWN_DIRECTORY,)
