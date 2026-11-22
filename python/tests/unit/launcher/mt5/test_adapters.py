"""The real (Windows) adapters of the MetaTrader 5 read ports (ADR 0038 § 6, I3). They run on the test machine's file system, inside ``tmp_path``,
and on nothing else: no registry write, no file write, no content read but ``origin.txt``."""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from trading_os.launcher.mt5 import ports
from trading_os.launcher.mt5.adapters import LocalMt5Files, WindowsInstalledPrograms

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows file system and registry")


class TestLocalFiles:
    def test_it_tells_files_from_folders_and_a_missing_path_from_both(self, tmp_path: Path) -> None:
        (tmp_path / "a folder").mkdir()
        (tmp_path / "terminal64.exe").write_bytes(b"MZ")
        files = LocalMt5Files()
        assert files.is_dir(str(tmp_path / "a folder")) and not files.is_file(str(tmp_path / "a folder"))
        assert files.is_file(str(tmp_path / "terminal64.exe")) and not files.is_dir(str(tmp_path / "terminal64.exe"))
        assert not files.is_dir(str(tmp_path / "missing")) and not files.is_file(str(tmp_path / "missing"))

    def test_a_directory_listing_names_entries_and_a_missing_directory_is_empty(self, tmp_path: Path) -> None:
        (tmp_path / "Advisors").mkdir()
        (tmp_path / "Robot.ex5").write_bytes(b"x")
        files = LocalMt5Files()
        entries = {entry.name: entry for entry in files.list_directory(str(tmp_path))}
        assert entries["Advisors"].is_dir is True
        assert entries["Robot.ex5"].is_dir is False
        assert files.list_directory(str(tmp_path / "missing")) == []

    @windows_only
    def test_a_junction_is_seen_as_a_link_with_its_target(self, tmp_path: Path) -> None:
        target = tmp_path / "the repository" / "mt5-execution-agent"
        target.mkdir(parents=True)
        experts = tmp_path / "Experts"
        experts.mkdir()
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(experts / "TradingOsAgent"), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert made.returncode == 0, made.stdout + made.stderr
        (entry,) = [e for e in LocalMt5Files().list_directory(str(experts)) if e.name == "TradingOsAgent"]
        assert entry.is_link is True
        assert entry.link_target is not None
        assert not entry.link_target.startswith(
            "\\\\?\\"
        )  # the extended-length prefix is an implementation detail, not a path to show
        assert Path(entry.link_target).resolve() == target.resolve()
        # remove the junction, never what it points to
        (experts / "TradingOsAgent").rmdir()
        assert target.is_dir()

    @pytest.mark.parametrize("encoding", ["utf-16", "utf-8", "utf-8-sig"])
    def test_origin_is_read_in_the_encodings_a_terminal_may_use(self, tmp_path: Path, encoding: str) -> None:
        (tmp_path / "origin.txt").write_text("C:\\Program Files\\MetaTrader 5\r\n", encoding=encoding)
        assert LocalMt5Files().read_origin(str(tmp_path)) == "C:\\Program Files\\MetaTrader 5"

    def test_no_origin_file_means_no_origin(self, tmp_path: Path) -> None:
        assert LocalMt5Files().read_origin(str(tmp_path)) is None

    def test_a_huge_or_binary_origin_file_is_not_trusted(self, tmp_path: Path) -> None:
        (tmp_path / "origin.txt").write_bytes(b"\x00\xff" * 50_000)
        assert LocalMt5Files().read_origin(str(tmp_path)) is None

    @windows_only
    def test_the_version_of_an_executable_is_read_from_its_resources(self) -> None:
        version = LocalMt5Files().file_version(sys.executable)
        assert version is not None
        assert version.split(".")[0] == str(sys.version_info.major)

    def test_the_version_of_a_missing_or_resourceless_file_is_none(self, tmp_path: Path) -> None:
        (tmp_path / "plain.exe").write_bytes(b"not a portable executable")
        files = LocalMt5Files()
        assert files.file_version(str(tmp_path / "missing.exe")) is None
        assert files.file_version(str(tmp_path / "plain.exe")) is None

    def test_it_writes_nothing(self, tmp_path: Path) -> None:
        (tmp_path / "origin.txt").write_text("C:\\x", encoding="utf-16")
        before = sorted(p.name for p in tmp_path.rglob("*"))
        files = LocalMt5Files()
        files.list_directory(str(tmp_path))
        files.read_origin(str(tmp_path))
        files.is_dir(str(tmp_path))
        assert sorted(p.name for p in tmp_path.rglob("*")) == before


class TestInstalledPrograms:
    @windows_only
    def test_the_registry_is_read_and_every_entry_has_a_name_and_a_tuple_of_locations(self) -> None:
        programs = WindowsInstalledPrograms().programs()
        assert programs, "a Windows machine lists at least one installed program"
        assert all(isinstance(p.display_name, str) and isinstance(p.locations, tuple) for p in programs)


class TestThePortsCanOnlyLook:
    def test_the_files_port_has_exactly_the_reading_methods(self) -> None:
        members = {name for name, _ in inspect.getmembers(ports.Mt5FilesPort) if not name.startswith("_")}
        assert members == {"is_dir", "is_file", "list_directory", "read_origin", "file_version", "experts_enabled"}

    def test_the_programs_port_has_one_reading_method(self) -> None:
        members = {name for name, _ in inspect.getmembers(ports.InstalledProgramsPort) if not name.startswith("_")}
        assert members == {"programs"}
