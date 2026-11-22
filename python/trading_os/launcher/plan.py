"""The start-up plan (ADR 0038, § 4): a pure function from what was observed to what a start would do.

Two rules shape it. A component that is already healthy is **kept** — never started again, never gated by what it depends on (only a *start*
depends on the links before it). A component that is there but not right (unhealthy, or its port held by something foreign) is **blocked**
with its reason: the launcher does not start a second copy over it and does not touch what it does not own.
"""

from __future__ import annotations

from trading_os.launcher.model import (
    Component,
    ComponentObservation,
    ComponentState,
    EnvironmentFacts,
    LauncherConfig,
    Observation,
    Plan,
    Reason,
    Stage,
    Step,
    StepAction,
)


def build_plan(observation: Observation, config: LauncherConfig) -> Plan:
    environment = observation.environment
    database = _database(observation.component(Component.DATABASE))
    core_observed = observation.component(Component.CORE)
    schema = _schema(database, core_observed, environment)
    core = _core(core_observed, schema, environment, config)
    cockpit = _cockpit(observation.component(Component.COCKPIT), core, environment, config)
    return Plan(steps=(database, schema, core, cockpit))


def _step(stage: Stage, action: StepAction, reason: Reason, detail: str = "", cwd: str | None = None) -> Step:
    return Step(stage=stage, action=action, reason=reason, detail=detail, working_directory=cwd)


def _present(stage: Stage, observed: ComponentObservation) -> Step | None:
    """What to do about a component that is already there. ``None`` when nothing is there and it may be started."""
    match observed.state:
        case ComponentState.HEALTHY:
            return _step(stage, StepAction.KEEP, Reason.ALREADY_HEALTHY, observed.detail)
        case ComponentState.STARTING:
            return _step(stage, StepAction.WAIT, Reason.STILL_STARTING, observed.detail)
        case ComponentState.FOREIGN:
            return _step(stage, StepAction.BLOCKED, Reason.FOREIGN_PROCESS, observed.detail)
        case ComponentState.UNHEALTHY:
            return _step(stage, StepAction.BLOCKED, Reason.UNHEALTHY, observed.detail)
        case ComponentState.UNAVAILABLE:
            return _step(stage, StepAction.BLOCKED, Reason.DOCKER_UNAVAILABLE, observed.detail)
        case ComponentState.ABSENT:
            return None


def _database(observed: ComponentObservation) -> Step:
    present = _present(Stage.DATABASE, observed)
    if present is not None:
        return present
    return _step(
        Stage.DATABASE, StepAction.START, Reason.NOT_RUNNING, "docker start du conteneur, puis attendre « healthy »"
    )


def _schema(database: Step, core: ComponentObservation, environment: EnvironmentFacts) -> Step:
    if core.state is ComponentState.HEALTHY:
        return _step(
            Stage.SCHEMA, StepAction.SKIP, Reason.SCHEMA_IN_USE, "le cœur est en ligne : le schéma est déjà utilisé"
        )
    if core.state is ComponentState.FOREIGN:
        return _step(
            Stage.SCHEMA, StepAction.BLOCKED, Reason.FOREIGN_PROCESS, "un processus étranger tient les ports du cœur"
        )
    if core.state is ComponentState.UNHEALTHY:
        return _step(
            Stage.SCHEMA,
            StepAction.BLOCKED,
            Reason.UNHEALTHY,
            "un cœur est là et ne répond pas : le schéma n'est pas touché",
        )
    if database.action is StepAction.BLOCKED:
        return _step(Stage.SCHEMA, StepAction.BLOCKED, Reason.DEPENDENCY_BLOCKED, "la base n'est pas utilisable")
    if not environment.venv_python_present:
        return _step(Stage.SCHEMA, StepAction.BLOCKED, Reason.VENV_MISSING, "l'environnement Python du cœur est absent")
    return _step(
        Stage.SCHEMA,
        StepAction.MIGRATE,
        Reason.SCHEMA_TO_APPLY,
        "migrations additives ; sauvegarde pg_dump avant toute migration en attente",
    )


def _core(observed: ComponentObservation, schema: Step, environment: EnvironmentFacts, config: LauncherConfig) -> Step:
    present = _present(Stage.CORE, observed)
    if present is not None:
        return present
    if not environment.venv_python_present:
        return _step(Stage.CORE, StepAction.BLOCKED, Reason.VENV_MISSING, "l'environnement Python du cœur est absent")
    if not environment.env_file_present:
        return _step(
            Stage.CORE, StepAction.BLOCKED, Reason.ENV_FILE_MISSING, ".env absent : les jetons locaux n'existent pas"
        )
    if schema.action is StepAction.BLOCKED:
        return _step(
            Stage.CORE, StepAction.BLOCKED, Reason.DEPENDENCY_BLOCKED, "la base ou le schéma n'est pas utilisable"
        )
    return _step(
        Stage.CORE,
        StepAction.START,
        Reason.NOT_RUNNING,
        "python -m trading_os serve, depuis le dossier python du dépôt",
        cwd=str(config.core_cwd),
    )


def _cockpit(observed: ComponentObservation, core: Step, environment: EnvironmentFacts, config: LauncherConfig) -> Step:
    present = _present(Stage.COCKPIT, observed)
    if present is not None:
        return present
    if not environment.npm_available:
        return _step(Stage.COCKPIT, StepAction.BLOCKED, Reason.NPM_MISSING, "npm est introuvable")
    if core.action is StepAction.BLOCKED:
        return _step(Stage.COCKPIT, StepAction.BLOCKED, Reason.DEPENDENCY_BLOCKED, "le cœur n'est pas utilisable")
    return _step(Stage.COCKPIT, StepAction.START, Reason.NOT_RUNNING, "npm run dev", cwd=str(config.cockpit_cwd))
