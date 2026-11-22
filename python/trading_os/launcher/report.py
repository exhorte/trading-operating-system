"""The launcher's plain-text reports (French, like ``start.ps1``) and their JSON form. Pure formatting: no I/O."""

from __future__ import annotations

from typing import Any

from trading_os.launcher.model import (
    Component,
    Observation,
    OutcomeStatus,
    Plan,
    Stage,
    StartReport,
    Step,
    StepAction,
    StopReport,
    StopStatus,
)
from trading_os.shared.time import iso

COMPONENT_LABELS = {Component.DATABASE: "base", Component.CORE: "cœur", Component.COCKPIT: "cockpit"}
STAGE_LABELS = {Stage.DATABASE: "base", Stage.SCHEMA: "schéma", Stage.CORE: "cœur", Stage.COCKPIT: "cockpit"}
ACTION_LABELS = {
    StepAction.KEEP: "garder",
    StepAction.START: "démarrer",
    StepAction.WAIT: "attendre",
    StepAction.MIGRATE: "migrer",
    StepAction.SKIP: "ignorer",
    StepAction.BLOCKED: "BLOQUÉ",
}


def _yes(value: bool, yes: str, no: str) -> str:
    return yes if value else no


def render_status(observation: Observation) -> str:
    environment = observation.environment
    lines = [
        f"Trading OS — état observé le {iso(observation.observed_at)} (lecture seule)",
        "",
        "Prérequis",
        f"  Docker           {_yes(environment.docker_available, 'répond', 'ne répond pas')}",
        f"  Python du cœur   {_yes(environment.venv_python_present, 'présent', 'ABSENT')}",
        f"  .env             {_yes(environment.env_file_present, 'présent', 'ABSENT')}",
        f"  npm              {_yes(environment.npm_available, 'trouvé', 'INTROUVABLE')}",
        "",
        "Composants",
    ]
    for item in observation.components:
        who = f"pid {item.pid}" if item.pid is not None else ""
        owner = "" if item.ownership.value == "NONE" else item.ownership.value
        lines.append(
            f"  {COMPONENT_LABELS[item.component]:<8} {item.state.value:<11} {owner:<11} {who:<10} {item.detail}".rstrip()
        )
        lines.extend(f"           ! {warning}" for warning in item.warnings)
    lines.append("")
    if observation.owned:
        lines.append("Processus possédés par le lanceur")
        lines.extend(
            f"  {COMPONENT_LABELS[entry.component]:<8} pid {entry.pid} depuis {iso(entry.started_at)}"
            for entry in observation.owned
        )
    else:
        lines.append("Processus possédés par le lanceur : aucun")
    if observation.registry_problem:
        lines.append(f"Registre : {observation.registry_problem} (il n'est pas utilisé)")
    return "\n".join(lines)


def _step_line(number: int, step: Step) -> str:
    text = f"  {number}. {STAGE_LABELS[step.stage]:<8} {ACTION_LABELS[step.action]:<9} {step.detail}".rstrip()
    if step.working_directory:
        text += f"\n     dossier : {step.working_directory}"
    if step.action is StepAction.BLOCKED:
        text += f"\n     raison : {step.reason.value}"
    return text


def render_plan(plan: Plan) -> str:
    lines = ["Plan de démarrage — lecture seule : rien n'est lancé.", ""]
    lines.extend(_step_line(number, step) for number, step in enumerate(plan.steps, start=1))
    lines.append("")
    if plan.blocked:
        lines.append("Résultat : bloqué — au moins une étape ne peut pas avancer (voir les raisons ci-dessus).")
    elif plan.changes_nothing:
        lines.append("Résultat : rien à faire, tout est déjà en place.")
    else:
        starts = ", ".join(STAGE_LABELS[step.stage] for step in plan.steps if step.action is not StepAction.KEEP)
        lines.append(f"Résultat : un démarrage ferait avancer : {starts}.")
    return "\n".join(lines)


OUTCOME_LABELS = {
    OutcomeStatus.DONE: "fait",
    OutcomeStatus.KEPT: "déjà en place",
    OutcomeStatus.SKIPPED: "rien à faire",
    OutcomeStatus.BLOCKED: "BLOQUÉ",
    OutcomeStatus.FAILED: "ÉCHEC",
}
STOP_LABELS = {
    StopStatus.STOPPED: "arrêté",
    StopStatus.WOULD_STOP: "serait arrêté",
    StopStatus.NOT_RUNNING: "ne tourne pas",
    StopStatus.NOT_OURS: "pas à moi",
    StopStatus.REFUSED: "REFUSÉ",
    StopStatus.FAILED: "ÉCHEC",
}


def render_start(report: StartReport) -> str:
    lines = ["Démarrage de Trading OS", ""]
    for number, item in enumerate(report.outcomes, start=1):
        lines.append(
            f"  {number}. {STAGE_LABELS[item.stage]:<8} {OUTCOME_LABELS[item.status]:<14} {item.detail}".rstrip()
        )
    lines.append("")
    if report.ok:
        lines.append(
            "Résultat : l'application est en place. Rien n'est armé, aucun compte n'est rattaché, aucun ordre n'est parti."
        )
    else:
        lines.append(
            "Résultat : incomplet — voir les étapes bloquées ou en échec ci-dessus (les journaux sont dans var/launcher/logs)."
        )
    return "\n".join(lines)


def render_stop(report: StopReport, *, dry_run: bool) -> str:
    lines = ["Arrêt de Trading OS" + (" — simulation : rien n'est arrêté" if dry_run else ""), ""]
    for item in report.outcomes:
        lines.append(f"  {COMPONENT_LABELS[item.component]:<8} {STOP_LABELS[item.status]:<14} {item.detail}".rstrip())
    lines.extend(f"  ! {warning}" for warning in report.warnings)
    lines.append("")
    lines.append(
        "MetaTrader 5 et son agent ne sont pas touchés ; aucune position n'est fermée, aucun ordre n'est envoyé."
    )
    return "\n".join(lines)


def to_document(observation: Observation, plan: Plan | None = None) -> dict[str, Any]:
    document: dict[str, Any] = {"observation": observation.model_dump(mode="json", by_alias=True)}
    if plan is not None:
        document["plan"] = plan.model_dump(mode="json", by_alias=True)
    return document
