"""``launcher mt5 build | builds | deploy`` (ADR 0039 § 7, I4). The machine is replaced by the fakes of the other MetaTrader tests, the terminal's data
folder and the launcher's state live under ``tmp_path``: a stray write is visible. Exit codes: 0 fine · 1 refused or failed · 2 the machine could not be read."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.launcher.mt5.support import declared, key
from tests.unit.launcher.mt5.support_deploy import TERMINAL_ID, FakeEditor, World
from tests.unit.launcher.support import T0
from trading_os.cli.main import main
from trading_os.launcher.mt5 import cli as mt5_cli
from trading_os.launcher.mt5.model import DiscoveryResult, Installation

EDITOR = "metaeditor64.exe"


@pytest.fixture
def machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    world = World(tmp_path, ea="directory")
    world.files.add_file(str(world.install) + "\\" + EDITOR, "5.0.0.6230")
    editor = FakeEditor()
    state = SimpleNamespace(world=world, editor=editor, tmp=tmp_path)
    monkeypatch.setattr(mt5_cli, "default_config", lambda: world.config)
    monkeypatch.setattr(mt5_cli, "make_files", lambda: world.files)
    monkeypatch.setattr(mt5_cli, "make_registry", lambda cfg: world.registry)
    monkeypatch.setattr(mt5_cli, "make_events", lambda cfg: world.events)
    monkeypatch.setattr(mt5_cli, "make_process_table", lambda: world.processes)
    monkeypatch.setattr(mt5_cli, "make_runner", lambda: state.editor)
    monkeypatch.setattr(
        mt5_cli,
        "_discover",
        lambda cfg, snapshot: DiscoveryResult(
            observed_at=T0,
            installations=(
                Installation(
                    install_path=str(world.install),
                    exe_path=str(world.install / "terminal64.exe"),
                    data_folders=(world.folder(),),
                ),
            ),
        ),
    )
    return state


class TestBuild:
    def test_it_compiles_a_copy_and_says_what_it_made(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID]) == 0
        out = capsys.readouterr().out
        assert "1.13" in out and "OBSERVE" in out and "0 erreur" in out
        assert machine.editor.calls, "MetaEditor was asked to compile the copy"
        assert any(args[0].lower().endswith(EDITOR) for args, _t, _c in machine.editor.calls)

    def test_an_unknown_terminal_is_a_refusal_that_starts_nothing(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["launcher", "mt5", "build", "--terminal", "NOPE"]) == 1
        assert "inconnu" in capsys.readouterr().err
        assert not machine.editor.calls

    def test_an_install_without_the_editor_is_a_refusal_that_starts_nothing(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        machine.world.files.files.discard(key(str(machine.world.install) + "\\" + EDITOR))
        assert main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID]) == 1
        assert "metaeditor64.exe" in capsys.readouterr().err
        assert not machine.editor.calls

    def test_compile_errors_are_reported_and_exit_one(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        machine.editor.errors = 2
        assert main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID]) == 1
        assert "2 erreur" in capsys.readouterr().err


class TestDeploy:
    def test_without_a_build_it_says_to_build_first(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["launcher", "mt5", "deploy", "--terminal", TERMINAL_ID]) == 1
        assert "launcher mt5 build" in capsys.readouterr().err

    def test_a_dry_run_shows_the_plan_and_writes_nothing(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID])
        capsys.readouterr()
        before = machine.world.tree()
        assert main(["launcher", "mt5", "deploy", "--terminal", TERMINAL_ID, "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "INSTALL" in out and "rien n'a été écrit" in out
        assert machine.world.tree() == before

    def test_it_deploys_and_says_what_it_wrote(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID])
        capsys.readouterr()
        assert main(["launcher", "mt5", "deploy", "--terminal", TERMINAL_ID]) == 0
        out = capsys.readouterr().out
        assert "déployé" in out.lower() and "TradingOsAgent.ex5" in out
        deployed = machine.world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5"
        assert deployed.is_file()
        assert machine.world.entry().deployment is not None

    def test_a_terminal_that_moved_is_refused_and_nothing_is_written(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID])
        capsys.readouterr()
        machine.world.files.origins[key(str(machine.world.data))] = r"C:\Elsewhere"
        assert main(["launcher", "mt5", "deploy", "--terminal", TERMINAL_ID]) == 1
        assert "MT5_TERMINAL_PATH_CHANGED" in capsys.readouterr().err
        assert not (machine.world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5").exists()


class TestBuilds:
    def test_it_lists_the_latest_build_and_writes_nothing(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID])
        capsys.readouterr()
        before = machine.world.tree()
        assert main(["launcher", "mt5", "builds"]) == 0
        assert "1.13" in capsys.readouterr().out
        assert machine.world.tree() == before

    def test_with_no_build_it_says_so(self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["launcher", "mt5", "builds"]) == 0
        assert "aucun build" in capsys.readouterr().out.lower()


class TestPrepare:
    def _deployed(self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]) -> None:
        machine.world.registry.declare(TERMINAL_ID, declared())
        main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID])
        main(["launcher", "mt5", "deploy", "--terminal", TERMINAL_ID])
        capsys.readouterr()

    def test_a_dry_run_shows_the_preset_and_writes_nothing(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._deployed(machine, capsys)
        before = machine.world.tree()
        assert main(["launcher", "mt5", "prepare", "--terminal", TERMINAL_ID, "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "InpMagicNumber=486046" in out and "InpAccountId=486046157" in out and "rien n'a été écrit" in out
        assert "InpTradableLogins=" in out and "token" not in out.lower()
        assert machine.world.tree() == before

    def test_it_writes_the_preset_and_the_startup_file(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._deployed(machine, capsys)
        assert main(["launcher", "mt5", "prepare", "--terminal", TERMINAL_ID]) == 0
        assert (machine.world.data / "MQL5" / "Presets" / f"TradingOS-{TERMINAL_ID}.set").is_file()
        assert (machine.world.config.var_dir / "mt5" / TERMINAL_ID / "startup.ini").is_file()
        assert machine.world.entry().prepared is not None

    def test_without_a_deployed_agent_it_is_refused(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        machine.world.registry.declare(TERMINAL_ID, declared())
        assert main(["launcher", "mt5", "prepare", "--terminal", TERMINAL_ID]) == 1
        assert "deploy" in capsys.readouterr().err

    def test_without_a_complete_declaration_it_is_refused_and_says_what_is_missing(
        self, machine: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["launcher", "mt5", "build", "--terminal", TERMINAL_ID])
        main(["launcher", "mt5", "deploy", "--terminal", TERMINAL_ID])
        capsys.readouterr()
        assert main(["launcher", "mt5", "prepare", "--terminal", TERMINAL_ID]) == 1
        err = capsys.readouterr().err
        assert "login attendu" in err and "numéro magique" in err
