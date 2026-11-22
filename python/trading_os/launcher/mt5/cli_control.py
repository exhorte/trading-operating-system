"""``python -m trading_os launcher mt5 start | status | verify`` (ADR 0038 § 8, ADR 0039 §§ 3 and 5, I6 and I7).

    start --terminal ID [--dry-run] [--confirm-close]
                            start a prepared terminal with our agent; an OPEN terminal is closed (politely, never killed) only after the gates all pass and the
                            phrase ``FERMER <terminal>`` is typed — read from standard input, there is no ``--yes``
    status [--terminal ID]  the state of the deployment of each terminal, from what is observed; a change of state is journalled
    verify --terminal ID    the core's reading of the conditions of technical readiness — read-only

None of them takes a password or a token, none connects or detaches an account, none changes a mode, none sends a command. ``start`` stops at the agent's hello: the
launcher never goes to ``CONFIRM``, ``ARMED`` or ``AUTONOMOUS``. Exit codes: 0 fine · 1 refused, blocked or failed · 2 the machine or the core could not be read.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from trading_os.launcher.events import new_correlation_id
from trading_os.launcher.lock import LauncherBusy
from trading_os.launcher.mt5 import cli as base
from trading_os.launcher.mt5.control import Mt5Controller, StartPlan, StartRefused, StartResult
from trading_os.launcher.mt5.journal import StateJournal
from trading_os.launcher.mt5.model import TerminalEntry, TerminalsSnapshot
from trading_os.launcher.mt5.states import DeploymentState
from trading_os.launcher.mt5.status import observe_terminal, render_observation, render_verify
from trading_os.launcher.mt5.terminals import RegistryRefused
from trading_os.launcher.ports import ProbeError
from trading_os.launcher.wiring import print_json, utf8_output
from trading_os.shared.time import SystemClock


def register_control(mt5: Any) -> None:
    start = mt5.add_parser(
        "start",
        help="start — or, after a typed confirmation, restart — a prepared terminal with our agent; never kills MetaTrader",
    )
    start.add_argument("--terminal", required=True, help="the registered terminal to start")
    start.add_argument(
        "--dry-run",
        action="store_true",
        help="show the gates and what would happen; an open terminal is read (positions, orders, login), nothing else is touched",
    )
    start.add_argument(
        "--confirm-close",
        action="store_true",
        help="allow closing an OPEN terminal: the phrase « FERMER <terminal> » is then read from standard input (there is no --yes)",
    )
    start.set_defaults(handler=run_start)
    status = mt5.add_parser("status", help="the state of the deployment of each terminal, from what is observed")
    status.add_argument("--terminal", help="only this terminal")
    status.add_argument("--json", action="store_true", help="print the states as JSON")
    status.set_defaults(handler=run_status)
    verify = mt5.add_parser(
        "verify", help="the core's reading of the conditions of technical readiness for a terminal — read-only"
    )
    verify.add_argument("--terminal", required=True, help="the registered terminal to verify")
    verify.set_defaults(handler=run_verify)


def _entry(snapshot: TerminalsSnapshot, terminal: str) -> TerminalEntry:
    if snapshot.problem:
        raise RegistryRefused([snapshot.problem])
    entry = snapshot.find(terminal)
    if entry is None:
        raise RegistryRefused(
            [f"terminal inconnu : {terminal} — « launcher mt5 list » liste ceux qui sont enregistrés"]
        )
    return entry


def _controller(config: Any, registry: Any, events: Any) -> Mt5Controller:
    return Mt5Controller(
        files=base.make_files(),
        processes=base.make_process_table(),
        spawner=base.make_spawner(),
        controller=base.make_controller_port(),
        probe=base.make_positions_probe(config),
        center=base.make_center_view(config),
        health=base.make_health(),
        registry=registry,
        events=events,
        clock=SystemClock(),
        sleeper=base.make_sleeper(),
        config=config,
        pid=os.getpid(),
    )


# ------------------------------------------------------------------------------------------------ start


def run_start(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = base.default_config()
        registry = base.make_registry(config)
        entry = _entry(registry.load(), args.terminal)
        controller = _controller(config, registry, base.make_events(config))
        plan = controller.plan(entry)
        print(render_start_plan(plan, entry, dry_run=args.dry_run))
        if args.dry_run:
            return 1 if plan.problems else 0
        if plan.problems:
            raise StartRefused(plan.problems)
        confirmation: str | None = None
        if plan.needs_close:
            if not args.confirm_close:
                raise StartRefused(
                    [
                        "CONFIRMATION : ce terminal est ouvert ; pour le fermer, relancez avec --confirm-close "
                        f"puis tapez exactement « {plan.confirmation_phrase} »"
                    ]
                )
            print(f"\nPour fermer ce terminal, tapez exactement : {plan.confirmation_phrase}")
            confirmation = sys.stdin.readline().rstrip("\r\n")
        result = controller.start(plan, confirmation=confirmation)
    except (RegistryRefused, StartRefused) as refused:
        for problem in refused.problems:
            print(f"refusé : {problem}", file=sys.stderr)
        return 1
    except LauncherBusy as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(render_start_result(result))
    return 1 if result.state is DeploymentState.EA_ERROR else 0


# ------------------------------------------------------------------------------------------------ status and verify


def run_status(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = base.default_config()
        registry = base.make_registry(config)
        snapshot = registry.load()
        if snapshot.problem:
            raise RegistryRefused([snapshot.problem])
        entries = [_entry(snapshot, args.terminal)] if args.terminal else list(snapshot.terminals)
        processes, center, clock = base.make_process_table(), base.make_center_view(config), SystemClock()
        journal = StateJournal(registry, base.make_events(config), clock)
        observations = [observe_terminal(item, processes=processes, center=center, clock=clock) for item in entries]
        for observation in observations:
            journal.record(
                observation.entry, observation.decision, trigger="observation", correlation_id=new_correlation_id()
            )
    except RegistryRefused as refused:
        for problem in refused.problems:
            print(f"refusé : {problem}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print_json(
            [
                {
                    "terminalId": o.entry.terminal_id,
                    "state": o.decision.state.value,
                    "codes": list(o.decision.codes),
                    "anomaly": o.decision.anomaly,
                    "running": o.running_pid is not None,
                    "deployed": o.deployed,
                    "coreReachable": o.center.reachable,
                    "helloReceived": o.center.hello_received,
                    "verdict": o.center.verdict.verdict if o.center.verdict else None,
                }
                for o in observations
            ]
        )
    elif not observations:
        print("Aucun terminal enregistré : « launcher mt5 plan » dit comment en enregistrer un.")
    else:
        print("\n\n".join(render_observation(o) for o in observations))
    return 0


def run_verify(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = base.default_config()
        entry = _entry(base.make_registry(config).load(), args.terminal)
        observation = observe_terminal(
            entry, processes=base.make_process_table(), center=base.make_center_view(config), clock=SystemClock()
        )
    except RegistryRefused as refused:
        for problem in refused.problems:
            print(f"refusé : {problem}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(render_verify(observation))
    if not observation.center.reachable:
        return 2
    verdict = observation.center.verdict
    return 1 if verdict is not None and verdict.verdict == "BLOCKED" else 0


# ------------------------------------------------------------------------------------------------ rendering


def render_start_plan(plan: StartPlan, entry: TerminalEntry, *, dry_run: bool) -> str:
    lines = [f"Démarrage contrôlé du terminal {entry.terminal_id} ({entry.label})"]
    lines += [f"  [{'OK   ' if gate.ok else 'REFUS'}] {gate.code} — {gate.detail}" for gate in plan.gates]
    if plan.snapshot is not None:
        lines.append("  (le terminal ouvert a été lu : positions, ordres en attente et login ; rien n'a été modifié)")
    if plan.problems:
        lines.append("\nBloqué : au moins une condition n'est pas remplie. Rien n'a été fermé, rien n'a été lancé.")
    elif plan.needs_close:
        lines.append(
            f"\nCe terminal est OUVERT (pid {plan.running_pid}) : il sera fermé poliment (jamais tué), puis relancé avec "
            f"{plan.startup_path}. Confirmation à taper : {plan.confirmation_phrase}"
        )
    else:
        lines.append(
            f"\nLe terminal est arrêté : il sera lancé avec {plan.startup_path} (aucun compte, aucun mot de passe sur la ligne de commande)."
        )
    if dry_run:
        lines.append("Simulation : rien n'a été fermé ni lancé.")
    return "\n".join(lines)


def render_start_result(result: StartResult) -> str:
    lines = [f"État : {result.state.value}" + (f" — {', '.join(result.codes)}" if result.codes else "")]
    if result.closed_previous:
        lines.append("Le terminal précédent a été fermé poliment, sans arrêt forcé.")
    if result.pid:
        lines.append(f"Terminal lancé (pid {result.pid}).")
    if result.hello_verified is True:
        lines.append(
            "L'agent a dit hello au cœur. La suite est la lecture du cœur : « launcher mt5 verify --terminal ID ». "
            "Le lanceur s'arrête ici : il ne passe jamais à CONFIRM, ARMED ni AUTONOMOUS."
        )
    lines.extend(f"- {note}" for note in result.notes)
    return "\n".join(lines)
