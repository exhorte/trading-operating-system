"""``TradingOS.bat`` and ``scripts/TradingOS.Launcher.ps1`` (ADR 0039, § 2): a thin wrapper that finds the repository, fixes the working directory
to ``04_code\\python``, picks a mode and calls ``python -m trading_os launcher …`` — and does nothing else.

The tests copy the two files into a temporary tree whose path contains **spaces** and put a *stub* ``trading_os`` package where the launcher
would be: it records how it was called. The real launcher, Docker, the cockpit and MetaTrader are never reached.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import trading_os

REPO = Path(trading_os.__file__).resolve().parents[2]  # …/04_code
# Both Windows PowerShell 5.1 (``powershell.exe``) and PowerShell 7 (``pwsh``) are exercised when present: 5.1 reads a script without a BOM
# as cp1252 and writes the console's code page, which is exactly where accents break.
WINDOWS_POWERSHELL = shutil.which("powershell")  # 5.1: reads a script without a BOM as cp1252 — where accents break
POWERSHELL_7 = shutil.which("pwsh")
SHELLS = [path for path in (WINDOWS_POWERSHELL, POWERSHELL_7) if path]
PREFERRED = POWERSHELL_7 or WINDOWS_POWERSHELL  # every case runs here; a targeted subset also runs on 5.1

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not SHELLS, reason="the wrapper is a Windows PowerShell script"
)

STUB = """\
import json
import os
import sys

with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
print("stub: " + " ".join(sys.argv[1:]))
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


@dataclass
class Tree:
    root: Path
    log: Path
    elsewhere: Path
    shell: str

    @property
    def ps1(self) -> Path:
        return self.root / "scripts" / "TradingOS.Launcher.ps1"

    @property
    def bat(self) -> Path:
        return self.root / "TradingOS.bat"

    def calls(self) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def argvs(self) -> list[list[str]]:
        return [call["argv"] for call in self.calls()]  # type: ignore[misc]


def make_tree(tmp_path: Path, shell: str) -> Tree:
    root = tmp_path / "Trading OS" / "04 code"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "TradingOS.Launcher.ps1", root / "scripts")
    shutil.copy(REPO / "TradingOS.bat", root)
    stub = root / "python" / "trading_os"
    stub.mkdir(parents=True)
    (stub / "__main__.py").write_text(STUB, encoding="utf-8")
    elsewhere = tmp_path / "somewhere else"
    elsewhere.mkdir()
    return Tree(root=root, log=tmp_path / "calls.jsonl", elsewhere=elsewhere, shell=shell)


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return make_tree(tmp_path, PREFERRED or "")


@pytest.fixture
def ps51_tree(tmp_path: Path) -> Tree:
    if WINDOWS_POWERSHELL is None:
        pytest.skip("Windows PowerShell 5.1 is not installed")
    return make_tree(tmp_path, WINDOWS_POWERSHELL)


@pytest.fixture
def batch_tree(tmp_path: Path) -> Tree:
    return make_tree(tmp_path, PREFERRED or "")


def environment(tree: Tree, exit_code: int = 0) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update({"STUB_LOG": str(tree.log), "STUB_EXIT": str(exit_code), "PYTHONUTF8": "1", "TRADINGOS_NOPAUSE": "1"})
    return env


def run_ps1(tree: Tree, *args: str, exit_code: int = 0, python: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [tree.shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tree.ps1), *args]
    if python != "":
        command += ["-PythonPath", python or sys.executable]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment(tree, exit_code),
        cwd=tree.elsewhere,
        timeout=120,
        check=False,
    )


def run_bat(tree: Tree, *args: str, exit_code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd", "/c", str(tree.bat), *args, "-PythonPath", sys.executable],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment(tree, exit_code),
        cwd=tree.elsewhere,
        timeout=120,
        check=False,
    )


class TestModes:
    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (["Status"], [["launcher", "status"]]),
            (["Status", "-Json"], [["launcher", "status", "--json"]]),
            (["Infrastructure"], [["launcher", "start"]]),
            (["Doctor"], [["launcher", "doctor"]]),
            (["Doctor", "-Json"], [["launcher", "doctor", "--json"]]),
            (["Stop"], [["launcher", "stop"]]),
            (["Stop", "-DryRun"], [["launcher", "stop", "--dry-run"]]),
            (["Stop", "-DryRun", "-IncludeDatabase"], [["launcher", "stop", "--dry-run", "--include-database"]]),
            (["MT5"], [["launcher", "mt5", "plan"]]),
            (["MT5", "-Json"], [["launcher", "mt5", "plan", "--json"]]),
            (["Full"], [["launcher", "start"], ["launcher", "mt5", "plan"]]),
        ],
    )
    def test_each_mode_calls_exactly_the_expected_subcommand(
        self, tree: Tree, args: list[str], expected: list[list[str]]
    ) -> None:
        result = run_ps1(tree, *args)
        assert result.returncode == 0, result.stdout + result.stderr
        assert tree.argvs() == expected

    def test_without_a_mode_it_is_full(self, tree: Tree) -> None:
        result = run_ps1(tree)
        assert result.returncode == 0, result.stdout + result.stderr
        assert tree.argvs() == [["launcher", "start"], ["launcher", "mt5", "plan"]]

    def test_the_mode_name_is_not_case_sensitive(self, tree: Tree) -> None:
        assert run_ps1(tree, "status").returncode == 0
        assert tree.argvs() == [["launcher", "status"]]

    def test_an_unknown_mode_is_refused_and_nothing_is_called(self, tree: Tree) -> None:
        result = run_ps1(tree, "Launch")
        assert result.returncode != 0
        assert tree.argvs() == []

    def test_dry_run_and_include_database_outside_stop_are_ignored_and_said_so(self, tree: Tree) -> None:
        result = run_ps1(tree, "Status", "-DryRun")
        assert result.returncode == 0
        assert tree.argvs() == [["launcher", "status"]]
        assert "-DryRun" in result.stdout and "ignoré" in result.stdout


class TestMetaTrader:
    def test_the_mt5_mode_only_plans_it_never_acts(self, tree: Tree) -> None:
        result = run_ps1(tree, "MT5")
        assert result.returncode == 0, result.stdout + result.stderr
        assert tree.argvs() == [["launcher", "mt5", "plan"]]

    def test_full_plans_metatrader_only_once_the_infrastructure_is_in_place(self, tree: Tree) -> None:
        assert run_ps1(tree, "Full").returncode == 0
        assert tree.argvs() == [["launcher", "start"], ["launcher", "mt5", "plan"]]

    @pytest.mark.parametrize("code", [1, 2])
    def test_a_start_that_fails_stops_full_before_the_mt5_plan(self, tree: Tree, code: int) -> None:
        result = run_ps1(tree, "Full", exit_code=code)
        assert result.returncode == code
        assert tree.argvs() == [["launcher", "start"]]

    def test_apply_changes_nothing_yet_and_the_wrapper_says_so(self, tree: Tree) -> None:
        result = run_ps1(tree, "Full", "-Apply")
        assert result.returncode == 0
        assert tree.argvs() == [["launcher", "start"], ["launcher", "mt5", "plan"]]
        assert "-Apply" in result.stdout and "sans effet" in result.stdout

    def test_in_json_mode_full_keeps_the_output_the_infrastructures_alone_and_says_where_the_rest_is(
        self, tree: Tree
    ) -> None:
        result = run_ps1(tree, "Full", "-Json")
        assert tree.argvs() == [["launcher", "start", "--json"]]
        assert "mt5" not in result.stdout.lower() and "MetaTrader" not in result.stdout
        assert "MT5 -Json" in result.stderr


class TestTheWrapperItself:
    def test_the_launcher_runs_from_the_python_directory_whatever_the_current_one(self, tree: Tree) -> None:
        run_ps1(tree, "Status")
        (call,) = tree.calls()
        assert Path(str(call["cwd"])).resolve() == (tree.root / "python").resolve()

    def test_a_path_with_spaces_is_not_a_problem(self, tree: Tree) -> None:
        assert " " in str(tree.root)
        assert run_ps1(tree, "Status").returncode == 0

    @pytest.mark.parametrize("code", [0, 1, 2])
    def test_the_exit_code_of_the_launcher_is_the_exit_code_of_the_wrapper(self, tree: Tree, code: int) -> None:
        for mode in (
            "Doctor",
            "Full",
        ):  # one mode that calls the launcher once, one that follows it with the MetaTrader plan
            assert run_ps1(tree, mode, exit_code=code).returncode == code, mode

    def test_a_missing_python_is_named_and_exits_two_without_calling_anything(self, tree: Tree) -> None:
        missing = str(tree.root / "no" / "python.exe")
        result = run_ps1(tree, "Status", python=missing)
        assert result.returncode == 2
        assert missing in result.stdout + result.stderr
        assert tree.argvs() == []

    def test_the_default_python_is_the_one_of_the_virtual_environment(self, tree: Tree) -> None:
        result = run_ps1(tree, "Status", python="")
        assert result.returncode == 2  # no .venv in the temporary tree: it looked there, and says where
        assert ".venv" in result.stdout + result.stderr

    def test_the_messages_keep_their_accents_even_when_the_output_is_redirected(self, tree: Tree) -> None:
        """Windows PowerShell 5.1 reads a script without a BOM as cp1252 and writes the console's code page: both must be UTF-8 here."""
        assert "incréments" in run_ps1(tree, "Full", "-Apply").stdout


class TestWindowsPowerShell51:
    """The same wrapper under the older shell that Windows ships: where a missing BOM, a code page or a quoting rule would show first."""

    def test_the_modes_call_the_expected_subcommands(self, ps51_tree: Tree) -> None:
        assert run_ps1(ps51_tree, "Status").returncode == 0
        assert run_ps1(ps51_tree, "Stop", "-DryRun").returncode == 0
        assert ps51_tree.argvs() == [["launcher", "status"], ["launcher", "stop", "--dry-run"]]

    def test_full_plans_metatrader_after_the_start(self, ps51_tree: Tree) -> None:
        assert run_ps1(ps51_tree, "Full").returncode == 0
        assert ps51_tree.argvs() == [["launcher", "start"], ["launcher", "mt5", "plan"]]

    def test_the_accents_survive_a_redirected_output(self, ps51_tree: Tree) -> None:
        """Without its BOM this script is read as cp1252 and « incréments » becomes « incrÃ©ments »."""
        assert "incréments" in run_ps1(ps51_tree, "Full", "-Apply").stdout

    @pytest.mark.parametrize("code", [1, 2])
    def test_the_exit_code_of_the_launcher_comes_through(self, ps51_tree: Tree, code: int) -> None:
        assert run_ps1(ps51_tree, "Doctor", exit_code=code).returncode == code

    def test_a_missing_python_is_named_and_exits_two(self, ps51_tree: Tree) -> None:
        missing = str(ps51_tree.root / "no" / "python.exe")
        result = run_ps1(ps51_tree, "Status", python=missing)
        assert result.returncode == 2
        assert missing in result.stdout + result.stderr


class TestTheBatchFile:
    def test_it_passes_the_arguments_through_and_runs_the_wrapper(self, batch_tree: Tree) -> None:
        result = run_bat(batch_tree, "Stop", "-DryRun")
        assert result.returncode == 0, result.stdout + result.stderr
        assert batch_tree.argvs() == [["launcher", "stop", "--dry-run"]]

    @pytest.mark.parametrize("code", [0, 1, 2])
    def test_it_returns_the_exit_code_of_the_wrapper(self, batch_tree: Tree, code: int) -> None:
        assert run_bat(batch_tree, "Status", exit_code=code).returncode == code

    def test_it_works_from_any_directory_and_from_a_path_with_spaces(self, batch_tree: Tree) -> None:
        assert run_bat(batch_tree, "Status").returncode == 0
        (call,) = batch_tree.calls()
        assert Path(str(call["cwd"])).resolve() == (batch_tree.root / "python").resolve()

    @pytest.mark.parametrize("code", [0, 2])
    def test_given_an_argument_it_never_pauses_so_a_terminal_user_is_not_asked_for_a_key(
        self, batch_tree: Tree, code: int
    ) -> None:
        """Launched from PowerShell, Python or a scheduler, a batch file also runs under ``cmd /c``: only the argument-less double-click may pause."""
        env = environment(batch_tree, code)
        env.pop("TRADINGOS_NOPAUSE")
        process = subprocess.Popen(
            ["cmd", "/c", str(batch_tree.bat), "Status", "-PythonPath", sys.executable],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=batch_tree.elsewhere,
        )
        try:
            output, _ = process.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            # kill the whole tree, or the pipes stay open and the test would hang with it
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False)
            process.communicate()
            pytest.fail("the batch file waited for a key although it was given an argument")
        assert process.returncode == code, output
        assert batch_tree.argvs() == [["launcher", "status"]]

    def test_the_final_pause_exists_only_for_the_argument_less_launch(self) -> None:
        text = (REPO / "TradingOS.bat").read_text(encoding="utf-8")
        assert re.search(r"^pause\s*$", text, re.MULTILINE)
        before_pause = re.split(r"^pause\s*$", text, maxsplit=1, flags=re.MULTILINE)[0]
        assert 'if not "%~1"=="" goto done' in before_pause
        assert "if defined TRADINGOS_NOPAUSE goto done" in before_pause
        assert "CMDCMDLINE" not in text  # the « /c » heuristic is what made a terminal user wait for a key
