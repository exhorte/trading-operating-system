"""``python -m trading_os launcher mt5 …`` (ADR 0039, I3).

    detect                       look for MetaTrader 5 terminals: installations, data folders, running instances — read-only
    list                         the registered terminals and what is still to declare — read-only
    plan                         what preparing MetaTrader 5 would take next — read-only
    register --terminal ID | --install-path DIR [--data-path DIR | --portable] [declarations]
                                 remember a terminal and what Exhorte declares about it

``register`` writes one thing: the launcher's own ``var/launcher/terminals.json`` (and an event). It writes nothing inside a MetaTrader folder, takes
no password and no token, and never picks a terminal for the user. Exit codes: 0 fine · 1 refused or failed · 2 the machine could not be read.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any

from trading_os.launcher.actions import SubprocessSpawner
from trading_os.launcher.adapters import HttpxProbe, SubprocessRunner
from trading_os.launcher.events import EventLog, EventType, new_correlation_id
from trading_os.launcher.lock import LauncherBusy
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.mt5.adapters import (
    HttpCenterView,
    LocalMt5Files,
    WindowsInstalledPrograms,
    WorkerPositionsProbe,
)
from trading_os.launcher.mt5.discovery import Mt5Discovery, data_folder_id, key_of, normalize, portable_id
from trading_os.launcher.mt5.model import (
    ChartSpec,
    DeclaredTerminal,
    DiscoveryResult,
    Mt5Config,
    Mt5Facts,
    TerminalEntry,
    TerminalSource,
    TerminalsSnapshot,
)
from trading_os.launcher.mt5.plan import build_mt5_plan, mt5_plan_document, render_mt5_plan
from trading_os.launcher.mt5.ports import CenterView, Mt5FilesPort, PositionsProbe
from trading_os.launcher.mt5.report import (
    describe_entry,
    detect_document,
    missing_text,
    render_detect,
    render_list,
)
from trading_os.launcher.mt5.terminals import RegistryRefused, TerminalRegistry
from trading_os.launcher.ports import (
    CommandRunner,
    HealthProbe,
    ProbeError,
    ProcessController,
    ProcessSpawner,
    Sleeper,
)
from trading_os.launcher.process_control import WindowsProcessController
from trading_os.launcher.wiring import RealSleeper, print_json, utf8_output
from trading_os.launcher.wiring import (
    default_config as default_config,  # re-exported: cli_ea and the tests use them through this module
)
from trading_os.launcher.wiring import make_process_table as make_process_table
from trading_os.shared.time import SystemClock


def register(launcher: Any) -> None:
    mt5 = launcher.add_parser(
        "mt5", help="MetaTrader 5 terminals: find them, remember them, plan their preparation (ADR 0039)"
    ).add_subparsers(dest="mt5_command", required=True)
    detect = mt5.add_parser("detect", help="look for MetaTrader 5 terminals — read-only")
    detect.add_argument("--json", action="store_true", help="print the result as JSON")
    detect.set_defaults(handler=run_detect)
    listing = mt5.add_parser("list", help="the registered terminals — read-only")
    listing.add_argument("--json", action="store_true", help="print the registry as JSON")
    listing.set_defaults(handler=run_list)
    plan = mt5.add_parser("plan", help="what preparing MetaTrader 5 would take next — read-only")
    plan.add_argument("--json", action="store_true", help="print the plan as JSON")
    plan.set_defaults(handler=run_plan)
    registering = mt5.add_parser(
        "register",
        help="remember a terminal and what you declare about it — writes only var/launcher/terminals.json",
    )
    which = registering.add_mutually_exclusive_group(required=True)
    which.add_argument("--terminal", help="the identifier shown by « launcher mt5 detect »")
    which.add_argument("--install-path", help="by hand: the folder holding terminal64.exe (when detection fails)")
    registering.add_argument(
        "--data-path", help="by hand: the terminal's data folder (its origin.txt must name the installation)"
    )
    registering.add_argument(
        "--portable", action="store_true", help="by hand: a portable terminal keeps its data in its installation folder"
    )
    registering.add_argument("--label", help="a name for this terminal (default: derived from its identifier)")
    registering.add_argument("--account-id", help="the Trading OS account this terminal serves")
    registering.add_argument("--expected-login", help="the broker login this terminal must be on (digits)")
    registering.add_argument("--symbol", help="the chart's symbol, as the broker names it (with --period)")
    registering.add_argument("--period", help="the chart's period: M1 … MN1 (with --symbol)")
    registering.add_argument(
        "--magic", type=int, help="the magic number of this terminal's EA (unique across terminals)"
    )
    registering.add_argument("--allowed-symbols", help="the symbols the EA may trade, comma-separated, broker names")
    registering.add_argument("--provider", help="the declared provider, for example EXNESS")
    registering.add_argument("--product", help="the declared product, for example EXNESS_STANDARD")
    registering.set_defaults(handler=run_register)
    from trading_os.launcher.mt5.cli_ea import register_ea  # here: cli_ea reads the wiring below, which tests replace

    register_ea(mt5)


# ------------------------------------------------------------------------------------------------ wiring (tests replace these)


def make_runner() -> CommandRunner:
    """Runs a command (MetaEditor, here) without a shell and without a window."""
    return SubprocessRunner()


def default_mt5_config() -> Mt5Config:
    roots = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Programs"))
    appdata = os.environ.get("APPDATA")
    return Mt5Config(
        program_roots=tuple(dict.fromkeys(root for root in roots if root)),
        data_root=os.path.join(appdata, "MetaQuotes", "Terminal") if appdata else None,
    )


def make_files() -> Mt5FilesPort:
    return LocalMt5Files()


def make_center_view(config: LauncherConfig) -> CenterView:
    """The core's System Center, asked over HTTP with the access key the core itself loads (it is held privately and never shown)."""
    from trading_os.app.config import get_settings

    settings = get_settings()
    key = settings.trading_os_cockpit_token.get_secret_value() if settings.trading_os_cockpit_token else None
    origin = (settings.allowed_origins.split(",")[0] or "http://127.0.0.1:3000").strip()
    return HttpCenterView(f"http://{config.api_host}:{config.api_port}", key, origin)


def make_health() -> HealthProbe:
    return HttpxProbe()


def make_spawner() -> ProcessSpawner:
    return SubprocessSpawner()


def make_controller_port() -> ProcessController:
    return WindowsProcessController(SubprocessRunner())


def make_sleeper() -> Sleeper:
    return RealSleeper()


def make_positions_probe(config: LauncherConfig) -> PositionsProbe:
    return WorkerPositionsProbe(make_runner(), config)


def make_discovery(config: LauncherConfig) -> Mt5Discovery:
    return Mt5Discovery(
        default_mt5_config(),
        files=make_files(),
        programs=WindowsInstalledPrograms(),
        processes=make_process_table(),
        clock=SystemClock(),
    )


def make_registry(config: LauncherConfig) -> TerminalRegistry:
    return TerminalRegistry(config.terminals_path, SystemClock(), make_process_table(), os.getpid())


def make_events(config: LauncherConfig) -> EventLog:
    return EventLog(config.events_dir, SystemClock())


def gather_facts(config: LauncherConfig) -> Mt5Facts:
    """What the diagnosis is given. A discovery that fails becomes a fact (``error``), not an exception: the rest of the diagnosis still runs."""
    snapshot = make_registry(config).load()
    try:
        discovery = make_discovery(config).discover(
            extra_install_paths=[entry.install_path for entry in snapshot.terminals]
        )
    except ProbeError as error:
        return Mt5Facts(snapshot=snapshot, error=str(error))
    return Mt5Facts(discovery=discovery, snapshot=snapshot)


def _discover(config: LauncherConfig, snapshot: TerminalsSnapshot) -> DiscoveryResult:
    return make_discovery(config).discover(extra_install_paths=[entry.install_path for entry in snapshot.terminals])


# ------------------------------------------------------------------------------------------------ read-only


def run_detect(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = default_config()
        result = _discover(config, make_registry(config).load())
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print_json(detect_document(result))
    else:
        print(render_detect(result))
    return 0


def run_list(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        snapshot = make_registry(default_config()).load()
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print_json(snapshot.model_dump(mode="json", by_alias=True))
    else:
        print(render_list(snapshot))
    return 0


def run_plan(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = default_config()
        snapshot = make_registry(config).load()
        plan = build_mt5_plan(_discover(config, snapshot), snapshot)
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print_json(mt5_plan_document(plan))
    else:
        print(render_mt5_plan(plan))
    return 0


# ------------------------------------------------------------------------------------------------ register


@dataclass(frozen=True)
class _Target:
    terminal_id: str
    install_path: str
    data_path: str
    portable: bool
    source: TerminalSource


def _discovered_target(config: LauncherConfig, terminal: str, snapshot: TerminalsSnapshot) -> _Target:
    for installation in _discover(config, snapshot).installations:
        for folder in installation.data_folders:
            if folder.terminal_id.lower() == terminal.lower():
                return _Target(
                    folder.terminal_id,
                    installation.install_path,
                    folder.path,
                    folder.portable,
                    TerminalSource.DISCOVERED,
                )
    raise RegistryRefused([f"terminal inconnu : {terminal} — « launcher mt5 detect » liste ceux qui sont détectés"])


def _manual_target(args: argparse.Namespace, files: Mt5FilesPort) -> _Target:
    install = normalize(args.install_path)
    if not files.is_file(install + "\\terminal64.exe"):
        raise RegistryRefused([f"terminal64.exe est introuvable dans {install}"])
    if args.portable:
        if args.data_path:
            raise RegistryRefused(
                ["--portable et --data-path s'excluent : un terminal portable garde ses données dans son dossier"]
            )
        if not files.is_dir(install + "\\MQL5"):
            raise RegistryRefused(
                [f"le dossier MQL5 est introuvable dans {install} : un terminal portable y garde ses données"]
            )
        return _Target(portable_id(install), install, install, True, TerminalSource.MANUAL)
    if not args.data_path:
        raise RegistryRefused(
            ["le dossier de données est obligatoire (--data-path), sauf pour un terminal portable (--portable)"]
        )
    data = normalize(args.data_path)
    if not files.is_dir(data):
        raise RegistryRefused([f"le dossier de données est introuvable : {data}"])
    origin = files.read_origin(data)
    if origin is None:
        raise RegistryRefused(
            [
                f"identité ambiguë : origin.txt est absent de {data} — le terminal n'attribue pas ce dossier à cette installation"
            ]
        )
    if key_of(origin) != key_of(install):
        raise RegistryRefused([f"identité ambiguë : origin.txt désigne {origin}, pas {install}"])
    return _Target(data_folder_id(data), install, data, False, TerminalSource.MANUAL)


def _merged(previous: DeclaredTerminal, args: argparse.Namespace) -> DeclaredTerminal:
    chart = previous.chart
    if args.symbol is not None or args.period is not None:
        symbol = args.symbol if args.symbol is not None else (previous.chart.symbol if previous.chart else None)
        period = args.period if args.period is not None else (previous.chart.period if previous.chart else None)
        if symbol is None or period is None:
            raise RegistryRefused(["le graphique demande un symbole et une période (--symbol et --period)"])
        chart = ChartSpec(symbol=symbol, period=period)
    allowed = previous.allowed_symbols
    if args.allowed_symbols is not None:
        allowed = tuple(item.strip() for item in args.allowed_symbols.split(",") if item.strip())
    return DeclaredTerminal(
        account_id=args.account_id if args.account_id is not None else previous.account_id,
        expected_login=args.expected_login if args.expected_login is not None else previous.expected_login,
        chart=chart,
        magic=args.magic if args.magic is not None else previous.magic,
        allowed_symbols=allowed,
        provider=args.provider if args.provider is not None else previous.provider,
        product=args.product if args.product is not None else previous.product,
    )


def run_register(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = default_config()
        registry = make_registry(config)
        snapshot = registry.load()
        if args.terminal:
            if args.data_path or args.portable:
                raise RegistryRefused(["--data-path et --portable ne vont qu'avec --install-path"])
            target = _discovered_target(config, args.terminal, snapshot)
        else:
            target = _manual_target(args, make_files())
        existing = snapshot.find(target.terminal_id)
        declared = _merged(existing.declared if existing else DeclaredTerminal(), args)
        if existing is not None:
            if args.label and args.label != existing.label:
                raise RegistryRefused([f"le nom d'un terminal enregistré ne se change pas ici ({existing.label})"])
            entry = registry.declare(target.terminal_id, declared)
        else:
            entry = registry.register(
                terminal_id=target.terminal_id,
                label=args.label or f"mt5-{target.terminal_id[:8].lower()}",
                install_path=target.install_path,
                data_path=target.data_path,
                portable=target.portable,
                source=target.source,
                declared=declared,
            )
    except RegistryRefused as refused:
        for problem in refused.problems:
            print(f"refusé : {problem}", file=sys.stderr)
        return 1
    except LauncherBusy as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    _announce(config, entry, updated=existing is not None)
    return 0


def _announce(config: LauncherConfig, entry: TerminalEntry, *, updated: bool) -> None:
    declared_names = [
        name for name in type(entry.declared).model_fields if getattr(entry.declared, name) not in (None, ())
    ]
    make_events(config).emit(
        EventType.MT5_TERMINAL_REGISTERED,
        component="mt5",
        correlation_id=new_correlation_id(),
        instance_id=entry.terminal_id,
        diagnostic=f"terminal {entry.label} {'mis à jour' if updated else 'enregistré'} ; champs déclarés : "
        + (", ".join(declared_names) or "aucun"),
    )
    print(f"Terminal {'mis à jour' if updated else 'enregistré'} :")
    print("\n".join(describe_entry(entry)))
    missing = missing_text(entry.declared)
    if missing:
        print(f"\n{missing}")
    print("\nSeul var/launcher/terminals.json a changé ; rien n'a été écrit dans MetaTrader 5.")
