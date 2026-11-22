"""``python -m trading_os launcher mt5 build | builds | deploy`` (ADR 0039 § 7, I4).

    build --terminal ID     compile the agent on a copy with the terminal's own MetaEditor and keep the build with its manifest
    builds                  the latest build and its manifest — read-only
    deploy --terminal ID [--dry-run]
                            put the latest build into the terminal (its ``.ex5`` only); ``--dry-run`` shows the plan and writes nothing

Neither command takes a password or a token, neither starts or stops MetaTrader, neither touches ``MQL5\\Files``. Exit codes: 0 fine · 1 refused or
failed · 2 the machine could not be read.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from trading_os.launcher.lock import LauncherBusy
from trading_os.launcher.mt5 import cli as base
from trading_os.launcher.mt5.build import AgentBuilder, BuildRefused, BuildResult
from trading_os.launcher.mt5.deploy import DeployAction, DeployPlan, DeployRefused, EaDeployer
from trading_os.launcher.mt5.manifest import BuildManifest, BuildStore
from trading_os.launcher.mt5.model import TerminalEntry, TerminalsSnapshot
from trading_os.launcher.mt5.prepare import PrepareAction, PreparePlan, Preparer, PrepareRefused
from trading_os.launcher.mt5.terminals import RegistryRefused
from trading_os.launcher.ports import ProbeError
from trading_os.launcher.wiring import utf8_output
from trading_os.shared.time import SystemClock

EDITOR_NAME = "metaeditor64.exe"


def register_ea(mt5: Any) -> None:
    build = mt5.add_parser(
        "build", help="compile the agent on a copy and keep the build with its manifest — writes only var/launcher/mt5"
    )
    build.add_argument("--terminal", required=True, help="the registered terminal whose MetaEditor compiles")
    build.add_argument(
        "--mode", choices=("observe", "confirm"), default="observe",
        help="observe (default): the agent never sends an order; confirm (ADR 0043): it can — its preset (tradable logins) and the core decide",
    )  # fmt: skip
    build.set_defaults(handler=run_build)
    builds = mt5.add_parser("builds", help="the latest build and its manifest — read-only")
    builds.set_defaults(handler=run_builds)
    deploy = mt5.add_parser(
        "deploy",
        help="put the latest build into a registered terminal — writes only its .ex5 (and the launcher's own state)",
    )
    deploy.add_argument("--terminal", required=True, help="the registered terminal to deploy to")
    deploy.add_argument("--dry-run", action="store_true", help="show what would be written and write nothing")
    deploy.set_defaults(handler=run_deploy)
    prepare = mt5.add_parser(
        "prepare",
        help="write the preset (MQL5/Presets) and the start-up file for a terminal that has our agent — writes nothing else",
    )
    prepare.add_argument("--terminal", required=True, help="the registered terminal to prepare")
    prepare.add_argument("--dry-run", action="store_true", help="show what would be written and write nothing")
    prepare.set_defaults(handler=run_prepare)
    from trading_os.launcher.mt5.cli_control import (
        register_control,  # same reason as in cli.register: it reads the wiring tests replace
    )

    register_control(mt5)


def _entry(snapshot: TerminalsSnapshot, terminal: str) -> TerminalEntry:
    if snapshot.problem:
        raise RegistryRefused([snapshot.problem])
    entry = snapshot.find(terminal)
    if entry is None:
        raise RegistryRefused(
            [f"terminal inconnu : {terminal} — « launcher mt5 list » liste ceux qui sont enregistrés"]
        )
    return entry


def _store(config: Any) -> BuildStore:
    return BuildStore(config.var_dir / "mt5" / "builds")


# ------------------------------------------------------------------------------------------------ build


def run_build(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = base.default_config()
        entry = _entry(base.make_registry(config).load(), args.terminal)
        files = base.make_files()
        editor = entry.install_path.rstrip("\\") + "\\" + EDITOR_NAME
        if not files.is_file(editor):
            raise BuildRefused(
                [f"{EDITOR_NAME} est introuvable dans {entry.install_path} : sans lui, rien n'est compilé"]
            )
        result = AgentBuilder(config, base.make_runner(), SystemClock(), base.make_events(config)).build(
            editor, editor_version=files.file_version(editor), mode=getattr(args, "mode", "observe").upper()
        )
    except (RegistryRefused, BuildRefused) as refused:
        for problem in refused.problems:
            print(f"refusé : {problem}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(render_build(result))
    print(
        "\nLa compilation s'est faite sur une copie ; seul var/launcher/mt5 a changé, rien n'a été écrit dans MetaTrader 5."
    )
    return 0


def run_builds(args: argparse.Namespace) -> int:
    utf8_output()
    latest = _store(base.default_config()).latest()
    if latest is None:
        print("Aucun build de l'agent : « launcher mt5 build --terminal ID » en fait un.")
        return 0
    manifest, ex5 = latest
    print(render_manifest(manifest, str(ex5)))
    return 0


# ------------------------------------------------------------------------------------------------ deploy


def run_deploy(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = base.default_config()
        registry = base.make_registry(config)
        snapshot = registry.load()
        entry = _entry(snapshot, args.terminal)
        latest = _store(config).latest()
        if latest is None:
            raise DeployRefused(["aucun build de l'agent : « launcher mt5 build --terminal ID » en fait un d'abord"])
        manifest, ex5 = latest
        folder = next(
            (
                data
                for installation in base._discover(config, snapshot).installations
                for data in installation.data_folders
                if data.terminal_id == entry.terminal_id
            ),
            None,
        )
        if folder is None:
            raise DeployRefused(
                [
                    f"le dossier de données du terminal {entry.terminal_id} n'est pas retrouvé : « launcher mt5 detect » dit où il en est"
                ]
            )
        deployer = EaDeployer(
            base.make_files(),
            config,
            SystemClock(),
            registry,
            base.make_events(config),
            base.make_process_table(),
            pid=os.getpid(),
        )
        plan = deployer.plan(entry, folder, manifest, ex5)
        print(render_plan(plan, entry, dry_run=args.dry_run))
        if args.dry_run:
            return 0
        deployer.apply(plan, ex5, manifest)
    except (RegistryRefused, DeployRefused) as refused:
        for problem in refused.problems:
            print(f"refusé : {problem}", file=sys.stderr)
        return 1
    except LauncherBusy as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"\nAgent {manifest.agent_version} déployé : {plan.target_file}")
    print(
        "Seuls ce fichier .ex5 et l'état du lanceur ont changé ; MQL5\\Files (magasin de commandes, jeton) n'a pas été touché, aucun terminal n'a été arrêté ni lancé."
    )
    return 0


# ------------------------------------------------------------------------------------------------ prepare


def run_prepare(args: argparse.Namespace) -> int:
    utf8_output()
    try:
        config = base.default_config()
        registry = base.make_registry(config)
        entry = _entry(registry.load(), args.terminal)
        preparer = Preparer(
            base.make_files(),
            config,
            SystemClock(),
            registry,
            base.make_events(config),
            base.make_process_table(),
            pid=os.getpid(),
        )
        plan = preparer.plan(entry)
        print(render_prepare(plan, entry, dry_run=args.dry_run))
        if args.dry_run:
            return 0
        preparer.apply(plan)
    except (RegistryRefused, PrepareRefused) as refused:
        for problem in refused.problems:
            print(f"refusé : {problem}", file=sys.stderr)
        return 1
    except LauncherBusy as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ProbeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(
        "\nPréparé : le preset (MQL5\\Presets) et le fichier de démarrage du lanceur ont été écrits ; aucun terminal ni agent n'a été touché."
    )
    return 0


# ------------------------------------------------------------------------------------------------ rendering


def render_prepare(plan: PreparePlan, entry: TerminalEntry, *, dry_run: bool) -> str:
    verbs = {
        PrepareAction.INSTALL: "à créer",
        PrepareAction.REPLACE: "à remplacer (l'ancien est gardé dans var/launcher/backups)",
        PrepareAction.UNCHANGED: "déjà à jour",
    }
    lines = [
        f"Préparation du terminal {entry.terminal_id} ({entry.label}) pour l'agent {plan.expert_path}",
        f"  preset : {plan.preset_path} — {verbs[plan.preset_action]}",
        f"  fichier de démarrage : {plan.startup_path} — {verbs[plan.startup_action]}",
        f"  graphique : {plan.chart.symbol} {plan.chart.period}",
        "  contenu du preset (aucun jeton, aucun mot de passe ; les listes de logins d'ordres restent vides) :",
        *(f"    {line}" for line in plan.preset_lines),
    ]
    if dry_run:
        lines.append("\nSimulation : rien n'a été écrit.")
    return "\n".join(lines)


def render_build(result: BuildResult) -> str:
    return render_manifest(result.manifest, str(result.ex5_path), heading="Build de l'agent")


def render_manifest(manifest: BuildManifest, ex5: str, *, heading: str = "Dernier build de l'agent") -> str:
    compilation = manifest.compilation
    capabilities = ", ".join(manifest.capabilities) if manifest.capabilities else "non lues dans la source"
    lines = [
        f"{heading} {manifest.agent_version} — compilé en {manifest.compiled_mode} (plafond {manifest.mode_ceiling}) le {manifest.compiled_at:%Y-%m-%d %H:%M} UTC",
        f"  .ex5 : {ex5}",
        f"  empreinte du .ex5 : {manifest.ex5_sha256} ({manifest.ex5_size} octets)",
        f"  compilation : {compilation.errors} erreur(s), {compilation.warnings} avertissement(s)"
        + (f" ; éditeur {manifest.editor_version}" if manifest.editor_version else ""),
        f"  sources : {len(manifest.sources)} fichier(s), empreinte globale {manifest.sources_sha256[:16]}…",
        f"  capacités annoncées : {capabilities}",
    ]
    return "\n".join(lines)


def render_plan(plan: DeployPlan, entry: TerminalEntry, *, dry_run: bool) -> str:
    kinds = {
        "JUNCTION": "à travers la jonction existante (respectée)",
        "DIRECTORY": "dans le dossier de l'agent installé",
        "NEW": "dans un dossier à nous, créé",
    }
    actions = {
        DeployAction.INSTALL: "INSTALL — aucun .ex5 à cet endroit",
        DeployAction.REPLACE: "REPLACE — un autre .ex5 est là : il est gardé dans var/launcher/backups, puis remplacé",
        DeployAction.UNCHANGED: "UNCHANGED — ce build est déjà en place, rien à copier",
    }
    lines = [
        f"Déploiement de l'agent {plan.agent_version} (build {plan.build_name}) sur le terminal {entry.terminal_id} ({entry.label})",
        f"  action : {actions[plan.action]}",
        f"  cible : {plan.target_file} — {kinds[plan.install_kind]}",
        f"  nom de l'agent pour MetaTrader : {plan.expert_path}",
    ]
    if dry_run:
        lines.append("\nSimulation : rien n'a été écrit.")
    return "\n".join(lines)
