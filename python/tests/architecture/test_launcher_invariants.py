"""Architecture invariants of the launcher (ADR 0038, § « Tests »), checked on the source so that no later increment can quietly break them:

* it prepares and observes — it imports nothing that decides, risks or executes;
* nothing ends a process outside an entry of the registry (in this increment there is no code that ends a process at all);
* it never writes what MetaTrader guards (`[Experts]`, `[Common]`, a login, a password), never fills the lists of logins an order may reach;
* it holds no secret in a model, no shell, no order function; and the port it uses to look at the environment cannot read a file.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import trading_os
from trading_os.domain.primitives import DomainModel
from trading_os.launcher import model as launcher_model
from trading_os.launcher import ports

LAUNCHER = Path(trading_os.__file__).parent / "launcher"


def sources() -> list[Path]:
    return sorted(path for path in LAUNCHER.rglob("*.py") if "__pycache__" not in path.parts)


def imports_of(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_the_launcher_package_exists_and_has_code() -> None:
    assert len(sources()) >= 8


def test_it_imports_nothing_that_decides_risks_or_executes() -> None:
    forbidden = (
        "trading_os.services",
        "trading_os.api",
        "trading_os.runtime",
        "trading_os.infrastructure",
        "trading_os.mcp",
        "trading_os.domain.execution",
        "trading_os.domain.risk",
        "trading_os.domain.guardian",
        "trading_os.domain.positions",
        "trading_os.domain.strategy",
        "trading_os.domain.autonomy",
        "MetaTrader5",
    )
    offenders = {
        f"{path.name} -> {name}"
        for path in sources()
        for name in imports_of(path)
        if any(name == bad or name.startswith(bad + ".") for bad in forbidden)
    }
    assert not offenders, offenders


def test_exactly_one_module_ends_a_process_and_it_is_the_one_that_is_named() -> None:
    pattern = re.compile(r"taskkill|Stop-Process|\.kill\(|\.terminate\(|os\.kill|signal\.|killpg", re.IGNORECASE)
    offenders = {path.name for path in sources() if pattern.search(path.read_text(encoding="utf-8"))}
    assert offenders == {"process_control.py"}, offenders


def test_only_the_stopper_hands_a_pid_to_the_controller_and_only_the_wiring_builds_it() -> None:
    callers = {
        path.name
        for path in sources()
        if re.search(r"\.(terminate_tree|request_stop)\(", path.read_text(encoding="utf-8"))
    }
    assert callers == {"stopper.py"}, callers
    importers = {path.name for path in sources() if "trading_os.launcher.process_control" in imports_of(path)}
    assert importers == {"cli.py"}, importers


def test_only_the_spawner_starts_a_process() -> None:
    offenders = {
        path.name
        for path in sources()
        if re.search(r"Popen\(|os\.startfile|CreateProcess", path.read_text(encoding="utf-8"))
    }
    assert offenders == {"actions.py"}, offenders


def test_only_the_metatrader_package_names_a_terminal_or_its_tools() -> None:
    """Finding and naming a terminal is the business of ``launcher/mt5/`` and of nothing else (ADR 0038 § 6, ADR 0039)."""
    pattern = re.compile(r"terminal64|metaeditor", re.IGNORECASE)
    outside = [path for path in sources() if "mt5" not in path.relative_to(LAUNCHER).parts[:-1]]
    assert not {path.name for path in outside if pattern.search(path.read_text(encoding="utf-8"))}


def test_no_command_goes_through_a_shell() -> None:
    pattern = re.compile(r"shell\s*=\s*True|os\.system\(|os\.popen\(|Invoke-Expression|\bcmd\s*/c\b", re.IGNORECASE)
    assert not {path.name for path in sources() if pattern.search(path.read_text(encoding="utf-8"))}


def test_it_never_writes_what_metatrader_guards() -> None:
    guarded = (
        "[Experts]",
        "[Common]",
        "AllowLiveTrading",
        "AllowDllImport",
        "Password=",
        "Login=",
        "InpTradableLogins",
        "InpClosableLogins",
    )
    offenders = {
        f"{path.name}: {needle}"
        for path in sources()
        for needle in guarded
        if needle in path.read_text(encoding="utf-8")
    }
    assert not offenders, offenders


def test_no_order_function_exists_in_the_launcher() -> None:
    pattern = re.compile(r"order_send|order_check|OrderSend|positions_close", re.IGNORECASE)
    assert not {path.name for path in sources() if pattern.search(path.read_text(encoding="utf-8"))}


def test_no_launcher_model_has_a_field_that_could_carry_a_secret() -> None:
    secret = re.compile(r"token|password|passwd|secret|credential|api_?key", re.IGNORECASE)
    offenders = []
    for module in (launcher_model,):
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, DomainModel) and cls.__module__ == module.__name__:
                offenders += [f"{cls.__name__}.{name}" for name in cls.model_fields if secret.search(name)]
    assert not offenders, offenders


def test_the_environment_port_can_only_look_for_a_path_or_a_tool_never_read_a_file() -> None:
    members = {name for name, _ in inspect.getmembers(ports.EnvironmentPort) if not name.startswith("_")}
    assert members == {"path_exists", "which"}


# ------------------------------------------------------------------------------------------------ I2b: the wrapper and the diagnosis

REPO = Path(trading_os.__file__).resolve().parents[2]
WRAPPERS = (REPO / "scripts" / "TradingOS.Launcher.ps1", REPO / "TradingOS.bat")


def test_the_wrapper_files_exist() -> None:
    assert all(path.is_file() for path in WRAPPERS), [str(path) for path in WRAPPERS if not path.is_file()]


def test_the_wrappers_find_the_python_and_call_the_launcher_and_do_nothing_else() -> None:
    """They hold no command that ends a process, reads the secrets file, touches Docker or MetaTrader, writes a file or changes a policy."""
    forbidden = re.compile(
        r"taskkill|Stop-Process|Invoke-Expression|\biex\b|Remove-Item|\bdel\s|\brmdir\b|Get-Content|\.env\b|docker|"
        r"Set-ExecutionPolicy|Set-Content|Out-File|Add-Content|New-Item|Start-Process|netsh|schtasks|reg\s+add|"
        r"terminal64|metaeditor|OrderSend|AllowLiveTrading",
        re.IGNORECASE,
    )
    offenders = {
        f"{path.name}: {match.group(0)}"
        for path in WRAPPERS
        for match in [forbidden.search(_commands_of(path))]
        if match
    }
    assert not offenders, offenders


# ADR 0038, A11 — « Docker Desktop éteint » — taken the other way by Exhorte on 2026-11-22 (« le lancer »): the batch file may call ONE dedicated script, and
# name the variable that skips it. Nothing else of Docker is allowed in the wrappers; the script has its own, narrower contract below.
DOCKER_SCRIPT = REPO / "scripts" / "TradingOS.Docker.ps1"
_DOCKER_STARTER_TOKENS = ("TradingOS.Docker.ps1", "TRADINGOS_NODOCKERSTART")


def _commands_of(path: Path) -> str:
    """What a wrapper *does*: its text without the comments of a batch file (``rem``) and without the two names that call and skip the Docker script."""
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".bat":
        text = "\n".join(line for line in text.splitlines() if not re.match(r"\s*rem(\s|$)", line, re.IGNORECASE))
        for token in _DOCKER_STARTER_TOKENS:
            text = text.replace(token, "")
    return text


def test_the_batch_file_calls_the_docker_script_in_the_start_modes_only_and_the_launcher_wrapper_never_mentions_docker() -> (
    None
):
    bat = (REPO / "TradingOS.bat").read_text(encoding="utf-8")
    assert "TradingOS.Docker.ps1" in bat and "TRADINGOS_NODOCKERSTART" in bat
    assert not re.search(r"docker", WRAPPERS[0].read_text(encoding="utf-8-sig"), re.IGNORECASE)


def test_the_docker_script_starts_docker_desktop_and_does_nothing_else() -> None:
    """It may launch the Docker Desktop executable it was given or found — once — and ask « docker info ». It ends nothing, removes nothing, reads and writes
    no file, touches no container, no secret, no MetaTrader."""
    raw = DOCKER_SCRIPT.read_text(encoding="utf-8-sig")
    code = "\n".join(
        line for line in re.sub(r"<#.*?#>", "", raw, flags=re.DOTALL).splitlines() if not line.lstrip().startswith("#")
    )
    forbidden = re.compile(
        r"taskkill|Stop-Process|Stop-Service|Invoke-Expression|\biex\b|Remove-Item|\bdel\s|\brmdir\b|Get-Content|\.env\b|"
        r"Set-ExecutionPolicy|Set-Content|Out-File|Add-Content|New-Item|netsh|schtasks|reg\s+add|"
        r"terminal64|metaeditor|OrderSend|AllowLiveTrading|compose|\brm\b|\bkill\b|\bstop\b|\brun\b",
        re.IGNORECASE,
    )
    match = forbidden.search(code)
    assert match is None, match.group(0) if match else ""
    launches = re.findall(r"Start-Process[^\n]*", code)
    assert len(launches) == 1 and "$exe" in launches[0]  # one launch, of the Docker Desktop executable it resolved
    assert re.findall(r"&\s*\$DockerCommand\s+(\w+)", code) == ["info"]  # the only thing it ever asks Docker


def test_the_execution_policy_is_bypassed_for_the_process_only_never_changed() -> None:
    text = (REPO / "TradingOS.bat").read_text(encoding="utf-8")
    assert re.search(r"-ExecutionPolicy\s+Bypass", text)
    assert "Set-ExecutionPolicy" not in text


def test_the_powershell_wrapper_carries_a_byte_order_mark_so_that_windows_powershell_reads_its_accents() -> None:
    assert (REPO / "scripts" / "TradingOS.Launcher.ps1").read_bytes().startswith(b"\xef\xbb\xbf")


def test_the_diagnosis_module_cannot_write_start_or_remove_anything() -> None:
    source = (LAUNCHER / "doctor.py").read_text(encoding="utf-8")
    pattern = re.compile(
        r"write_text|write_bytes|\bopen\(|unlink|mkdir|rename|rmtree|os\.remove|Popen|subprocess|LauncherLock|"
        r"ProcessRegistry|EventLog|\.save\(",
        re.IGNORECASE,
    )
    assert not pattern.search(source), pattern.search(source)


def test_the_doctor_command_takes_no_lock_starts_nothing_and_stops_nothing() -> None:
    tree = ast.parse((LAUNCHER / "cli.py").read_text(encoding="utf-8"))
    (function,) = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "run_doctor"]
    body = ast.unparse(function)
    for name in ("LauncherLock", "Starter", "Stopper", "adopt", "spawner", "controller", "registry.save", "events"):
        assert name not in body, name


def test_inspecting_the_lock_is_read_only() -> None:
    tree = ast.parse((LAUNCHER / "lock.py").read_text(encoding="utf-8"))
    (function,) = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inspect_lock"]
    body = ast.unparse(function)
    assert not re.search(r"unlink|write|os\.open|mkdir|rename", body), body


# ------------------------------------------------------------------------------------------------ I3: the MetaTrader package

MT5 = LAUNCHER / "mt5"


def mt5_sources() -> list[Path]:
    return sorted(path for path in MT5.rglob("*.py") if "__pycache__" not in path.parts)


def test_the_metatrader_package_exists_and_has_its_modules() -> None:
    expected = {"model.py", "ports.py", "adapters.py", "discovery.py", "terminals.py", "plan.py", "cli.py", "report.py"}
    assert expected <= {path.name for path in mt5_sources()}


# The modules of ``launcher/mt5`` that write, and what each may write (ADR 0039 §§ 4 and 7). Everything else there only reads.
WRITERS = {
    "terminals.py": "the launcher's own registry, var/launcher/terminals.json",
    "manifest.py": "the builds, under var/launcher/mt5/builds",
    "build.py": "its working copy, under var/launcher/mt5/work, and the builds",
    "deploy.py": "one file of a terminal — the .ex5 of our agent — and backups under var/launcher/backups",
    "prepare.py": "one file of a terminal — its preset in MQL5/Presets — the launcher's own start-up file, and backups",
}


def test_only_the_registry_module_writes_anything_and_nothing_touches_a_metatrader_folder() -> None:
    """Finding terminals is reading. Only the modules of ``WRITERS`` write, each to the place it is named for."""
    write = re.compile(
        r"write_text|write_bytes|open\([^)]*[\"'](?:w|a|x)b?[\"']|os\.replace|mkdir|unlink|rmtree|shutil|os\.remove|rename|copyfile|"
        r"winreg\.(?:SetValue|SetValueEx|CreateKey|CreateKeyEx|DeleteKey|DeleteValue)|\.touch\(",
        re.IGNORECASE,
    )
    offenders = {
        path.name
        for path in mt5_sources()
        if path.name not in WRITERS and write.search(path.read_text(encoding="utf-8"))
    }
    assert not offenders, offenders


def test_the_metatrader_models_hold_no_field_for_a_secret_or_for_a_command_line() -> None:
    """A terminal can be started with ``/login:`` and ``/password:``: its command line is read for two facts and never kept."""
    from trading_os.launcher.mt5 import model as mt5_model

    forbidden = re.compile(
        r"token|password|passwd|secret|credential|api_?key|command|cmdline|argv|argument", re.IGNORECASE
    )
    offenders = []
    for _, cls in inspect.getmembers(mt5_model, inspect.isclass):
        if issubclass(cls, DomainModel) and cls.__module__ == mt5_model.__name__:
            offenders += [f"{cls.__name__}.{name}" for name in cls.model_fields if forbidden.search(name)]
    assert not offenders, offenders


def test_no_metatrader_command_has_an_option_for_a_password_or_a_token() -> None:
    import argparse

    from trading_os.cli.main import build_parser

    def subparser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction) and name in action.choices:
                return action.choices[name]
        raise AssertionError(name)

    def options(parser: argparse.ArgumentParser) -> list[str]:
        found: list[str] = []
        for action in parser._actions:
            found += action.option_strings
            if isinstance(action, argparse._SubParsersAction):
                for child in action.choices.values():
                    found += options(child)
        return found

    mt5 = subparser(subparser(build_parser(), "launcher"), "mt5")
    names = options(mt5)
    assert "--expected-login" in names and "--magic" in names  # the walk reached the registration options
    assert not [name for name in names if re.search(r"password|passwd|token|secret|key", name, re.IGNORECASE)], names


def test_the_diagnosis_may_import_the_metatrader_model_but_not_its_writer() -> None:
    imported = imports_of(LAUNCHER / "doctor.py")
    assert "trading_os.launcher.mt5.model" in imported
    assert "trading_os.launcher.mt5.terminals" not in imported


def _string_constants(path: Path) -> set[str]:
    """Every string literal of a module except its docstrings — what the code *names*, not what it explains."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    }


def test_the_deployer_names_no_part_of_a_terminal_but_the_experts_folder() -> None:
    """ADR 0039 § 4, rule 5: the command store of the EA and the token (MQL5/Files), the presets, the profiles, the configuration — never from here.
    Only the literals that *name* something are read (one word, no sentence): the messages shown to a person are not paths."""
    named = " ".join(sorted(word for word in _string_constants(MT5 / "deploy.py") if len(word.split()) == 1)).lower()
    for part in ("files", "presets", "profiles", "common.ini", "config", ".token", "origin.txt"):
        assert part not in named, part
    assert "experts" in named


def test_the_builder_and_the_manifest_never_name_a_terminal_folder() -> None:
    for module in ("build.py", "manifest.py"):
        named = " ".join(sorted(word for word in _string_constants(MT5 / module) if len(word.split()) == 1)).lower()
        for part in ("mql5", "experts", "files", "presets", "profiles", "common.ini"):
            assert part not in named, (module, part)


def test_only_the_builder_names_the_compiler_and_only_with_a_copy() -> None:
    """MetaEditor is started by ``build.py`` on the working copy: no other module of the package starts it or names its arguments."""
    pattern = re.compile(r"/compile:|/log:", re.IGNORECASE)
    assert {path.name for path in mt5_sources() if pattern.search(path.read_text(encoding="utf-8"))} == {"build.py"}


def test_the_preparer_names_no_part_of_a_terminal_but_its_presets_folder() -> None:
    named = " ".join(sorted(word for word in _string_constants(MT5 / "prepare.py") if len(word.split()) == 1)).lower()
    for part in ("experts", "files", "profiles", "common.ini", "origin.txt", ".token"):
        assert part not in named, part
    assert "presets" in named


def test_the_preset_and_the_startup_file_are_pure() -> None:
    """They make bytes and text from what they are given: they import nothing that reads a file, an environment or a process."""
    allowed = {"__future__", "re", "collections.abc", "dataclasses", "trading_os.launcher.mt5.model"}
    for module in ("preset.py", "startup_ini.py"):
        assert imports_of(MT5 / module) <= allowed, (module, imports_of(MT5 / module) - allowed)


# ------------------------------------------------------------------------------------------------ I6 and I7: the controlled start and the reading


def test_only_the_controlled_start_asks_a_terminal_to_close_and_nothing_ever_kills_one() -> None:
    callers = {
        path.name for path in sources() if re.search(r"\.request_window_close\(", path.read_text(encoding="utf-8"))
    }
    assert callers == {"control.py"}, callers
    control = (MT5 / "control.py").read_text(encoding="utf-8")
    assert not re.search(r"terminate_tree|request_stop|taskkill|\.kill\(|\.terminate\(", control)


def test_the_controlled_start_asks_for_the_typed_phrase_before_it_closes_anything() -> None:
    """The close request comes after the confirmation check in the source, and the phrase is compared for equality — no option, no default."""
    source = (MT5 / "control.py").read_text(encoding="utf-8")
    assert source.index("confirmation != plan.confirmation_phrase") < source.index("request_window_close")
    assert not re.search(r"confirmation\s*=\s*plan\.confirmation_phrase|assume_yes|auto_confirm", source)


def test_the_core_never_imports_the_launcher() -> None:
    """The System Center and the launcher meet in two JSON files, never in code: the core reads them with its own readers."""
    core = Path(trading_os.__file__).parent
    offenders = {
        str(path.relative_to(core))
        for folder in ("services", "api", "domain", "infrastructure", "runtime", "app", "shared", "mcp")
        for path in (core / folder).rglob("*.py")
        if "(" not in path.name and any(name.startswith("trading_os.launcher") for name in imports_of(path))
    }
    assert not offenders, offenders


def test_the_launcher_does_not_import_the_services_that_decide_and_reads_the_core_only_over_http() -> None:
    http_reader = (MT5 / "adapters.py").read_text(encoding="utf-8")
    assert "api/system/mt5/terminals" in http_reader
    assert not re.search(r"\.post\(|\.put\(|\.delete\(|\.patch\(", http_reader), "the launcher only ever reads the core"


def test_no_launcher_module_prints_or_stores_the_core_access_key() -> None:
    """The key is held privately by the HTTP adapter: not in a model, not in an event, not in a message."""
    for path in sources():
        text = path.read_text(encoding="utf-8")
        assert "print(access_key" not in text and "print(key" not in text, path.name
        assert not re.search(r"emit\([^)]*access_key", text), path.name
