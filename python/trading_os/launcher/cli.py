"""``python -m trading_os launcher …`` (ADR 0038).

    plan                         what a start would do from what is observed now — read-only
    status                       what is observed now: prerequisites, components, owners — read-only
    doctor                       what is wrong and what to do about it (ADR 0039) — read-only, takes no lock, repairs nothing
    start                        start what is missing, in order, waiting for each link to be really healthy; a healthy component is left alone
    stop [--dry-run] [--include-database]
                                 stop what the launcher started (cockpit, core, then the database if it started it); nothing else
    adopt core | cockpit         make a process started by hand one the launcher owns, so that ``stop`` may end it
    mt5 detect | list | plan     look for MetaTrader 5 terminals, list the registered ones, say what preparing them would take — read-only (ADR 0039)
    mt5 register …               remember a terminal and what Exhorte declares about it — writes only var/launcher/terminals.json

Exit codes: 0 fine · 1 something is blocked, refused or failed, or another launcher is running · 2 the machine could not be observed (fails closed).
``start`` and ``stop`` never arm anything, attach no account, touch no MetaTrader terminal, close no position and send no order.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any

from trading_os.launcher.actions import DockerActionsCli, SubprocessSpawner
from trading_os.launcher.adapters import DockerCli, HttpxProbe, LocalEnvironment, SubprocessRunner, WindowsProcessTable
from trading_os.launcher.adopt import adopt
from trading_os.launcher.doctor import diagnose, doctor_document, render_doctor
from trading_os.launcher.events import EventLog, new_correlation_id
from trading_os.launcher.lock import LauncherBusy, LauncherLock, inspect_lock
from trading_os.launcher.model import Component, LauncherConfig
from trading_os.launcher.mt5.cli import gather_facts as gather_mt5_facts
from trading_os.launcher.mt5.cli import register as register_mt5
from trading_os.launcher.observe import Observer
from trading_os.launcher.plan import build_plan
from trading_os.launcher.ports import (
    CommandRunner,
    DockerActions,
    DockerPort,
    EnvironmentPort,
    ProbeError,
    ProcessController,
    ProcessSpawner,
    ProcessTable,
    Sleeper,
)
from trading_os.launcher.process_control import WindowsProcessController
from trading_os.launcher.registry import ProcessRegistry
from trading_os.launcher.report import render_plan, render_start, render_status, render_stop, to_document
from trading_os.launcher.starter import Starter
from trading_os.launcher.stopper import Stopper
from trading_os.launcher.wiring import RealSleeper, default_config, make_process_table
from trading_os.launcher.wiring import print_json as _print_json
from trading_os.launcher.wiring import utf8_output as _utf8_output
from trading_os.shared.time import Clock, SystemClock


@dataclass(frozen=True)
class Runtime:
    """Every port the launcher uses, wired once. Tests hand the commands a simulated machine through ``make_runtime``."""

    observer: Observer
    docker: DockerPort
    actions: DockerActions
    runner: CommandRunner
    spawner: ProcessSpawner
    controller: ProcessController
    processes: ProcessTable
    environment: EnvironmentPort
    registry: ProcessRegistry
    events: EventLog
    clock: Clock
    sleeper: Sleeper
    own_pid: int


def register(commands: Any) -> None:
    launcher = commands.add_parser(
        "launcher", help="the launcher: look at the machine, plan, start and stop what it started (ADR 0038)"
    ).add_subparsers(dest="launcher_command", required=True)
    plan = launcher.add_parser("plan", help="what a start would do — nothing is started")
    plan.add_argument("--json", action="store_true", help="print the observation and the plan as JSON")
    plan.set_defaults(handler=run_plan)
    status = launcher.add_parser("status", help="what is running, who owns it — nothing is changed")
    status.add_argument("--json", action="store_true", help="print the observation as JSON")
    status.set_defaults(handler=run_status)
    doctor = launcher.add_parser(
        "doctor", help="explain what is wrong and what to do about it — read-only, nothing is changed (ADR 0039)"
    )
    doctor.add_argument("--json", action="store_true", help="print the diagnosis as JSON")
    doctor.set_defaults(handler=run_doctor)
    start = launcher.add_parser("start", help="start what is missing, in order; a healthy component is left alone")
    start.add_argument("--json", action="store_true", help="print the report as JSON")
    start.set_defaults(handler=run_start)
    stop = launcher.add_parser("stop", help="stop what the launcher started — never MetaTrader, never a position")
    stop.add_argument("--dry-run", action="store_true", help="say what would be stopped, stop nothing")
    stop.add_argument(
        "--include-database",
        action="store_true",
        help="also stop the database container, even if the launcher did not start it",
    )
    stop.add_argument("--json", action="store_true", help="print the report as JSON")
    stop.set_defaults(handler=run_stop)
    adopting = launcher.add_parser(
        "adopt", help="own a process started by hand (recognized as this repository's), so that stop may end it"
    )
    adopting.add_argument(
        "component", choices=[Component.CORE.value, Component.COCKPIT.value, Component.DATABASE.value]
    )
    adopting.set_defaults(handler=run_adopt)
    register_mt5(launcher)


def make_runtime(config: LauncherConfig) -> Runtime:
    if sys.platform != "win32":
        raise ProbeError("le lanceur ne sait travailler que sous Windows")
    runner = SubprocessRunner()
    clock = SystemClock()
    processes = WindowsProcessTable(runner)
    docker = DockerCli(runner)
    registry = ProcessRegistry(config.registry_path, clock)
    return Runtime(
        observer=Observer(
            config,
            processes=processes,
            docker=docker,
            health=HttpxProbe(),
            environment=LocalEnvironment(),
            registry=registry,
            clock=clock,
        ),
        docker=docker,
        actions=DockerActionsCli(runner),
        runner=runner,
        spawner=SubprocessSpawner(),
        controller=WindowsProcessController(runner),
        processes=processes,
        environment=LocalEnvironment(),
        registry=registry,
        events=EventLog(config.events_dir, clock),
        clock=clock,
        sleeper=RealSleeper(),
        own_pid=os.getpid(),
    )


def make_observer(config: LauncherConfig) -> Observer:
    return make_runtime(config).observer


# ------------------------------------------------------------------------------------------------ read-only


def run_plan(args: argparse.Namespace) -> int:
    _utf8_output()
    try:
        config = default_config()
        observation = make_observer(config).observe()
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    plan = build_plan(observation, config)
    if args.json:
        _print_json(to_document(observation, plan))
    else:
        print(render_plan(plan))
    return 1 if plan.blocked else 0


def run_status(args: argparse.Namespace) -> int:
    _utf8_output()
    try:
        observation = make_observer(default_config()).observe()
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        _print_json(to_document(observation))
    else:
        print(render_status(observation))
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    """Read-only like ``plan`` and ``status``: it takes no lock, writes nothing, removes nothing — not even a stale lock."""
    _utf8_output()
    try:
        config = default_config()
        observation = make_observer(config).observe()
        lock = inspect_lock(config.lock_path, make_process_table())
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    report = diagnose(observation, config, lock, mt5=gather_mt5_facts(config))
    if args.json:
        _print_json(doctor_document(report))
    else:
        print(render_doctor(report))
    return 0 if report.ok else 1


# ------------------------------------------------------------------------------------------------ acting


def run_start(args: argparse.Namespace) -> int:
    _utf8_output()
    try:
        config = default_config()
        runtime = make_runtime(config)
        with LauncherLock(config.lock_path, runtime.processes, runtime.clock, pid=runtime.own_pid):
            report = Starter(
                config,
                observer=runtime.observer,
                docker=runtime.docker,
                actions=runtime.actions,
                runner=runtime.runner,
                spawner=runtime.spawner,
                processes=runtime.processes,
                environment=runtime.environment,
                registry=runtime.registry,
                events=runtime.events,
                clock=runtime.clock,
                sleeper=runtime.sleeper,
                correlation_id=new_correlation_id(),
            ).start()
    except LauncherBusy as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        _print_json(report.model_dump(mode="json", by_alias=True))
    else:
        print(render_start(report))
    return 0 if report.ok else 1


def run_stop(args: argparse.Namespace) -> int:
    _utf8_output()
    try:
        config = default_config()
        runtime = make_runtime(config)

        def stop() -> Any:
            return Stopper(
                config,
                observer=runtime.observer,
                docker=runtime.docker,
                actions=runtime.actions,
                controller=runtime.controller,
                processes=runtime.processes,
                registry=runtime.registry,
                events=runtime.events,
                clock=runtime.clock,
                sleeper=runtime.sleeper,
                correlation_id=new_correlation_id(),
            ).stop(include_database=args.include_database, dry_run=args.dry_run)

        if args.dry_run:
            report = stop()  # looks only: no lock, nothing written
        else:
            with LauncherLock(config.lock_path, runtime.processes, runtime.clock, pid=runtime.own_pid):
                report = stop()
    except LauncherBusy as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        _print_json(report.model_dump(mode="json", by_alias=True))
    else:
        print(render_stop(report, dry_run=args.dry_run))
    return 0 if report.ok else 1


def run_adopt(args: argparse.Namespace) -> int:
    _utf8_output()
    try:
        config = default_config()
        runtime = make_runtime(config)
        with LauncherLock(config.lock_path, runtime.processes, runtime.clock, pid=runtime.own_pid):
            outcome = adopt(
                Component(args.component),
                observer=runtime.observer,
                processes=runtime.processes,
                registry=runtime.registry,
                events=runtime.events,
                clock=runtime.clock,
                correlation_id=new_correlation_id(),
            )
    except LauncherBusy as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(outcome.detail if outcome.adopted else f"refusé : {outcome.detail}")
    return 0 if outcome.adopted else 1
