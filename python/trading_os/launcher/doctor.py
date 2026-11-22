"""``launcher doctor`` (ADR 0039, § 6 — I2b, infrastructure side): explain what the launcher can observe, and what to do about it.

A **pure** function of an observation, of the lock's state and of the configuration: it asks the machine nothing, changes nothing, starts nothing, and
stops nothing. It explains; it never repairs. Everything it cannot see it says it cannot see — MetaTrader, the terminal, the EA and the chart are not
inspected by the launcher yet (increments I3 to I7), and no state is invented for them.

Severities: ``OK`` is as it should be · ``INFO`` is a fact worth knowing, not a fault · ``WARNING`` deserves a look · ``PROBLEM`` stops Trading OS from
working or being started · ``UNKNOWN`` could not be judged. Only a ``PROBLEM`` makes the report not ``ok``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from trading_os.domain.primitives import DomainModel
from trading_os.launcher.lock import LockInspection, LockState
from trading_os.launcher.model import (
    Component,
    ComponentObservation,
    ComponentState,
    CoreHealth,
    LauncherConfig,
    Observation,
    Ownership,
)
from trading_os.launcher.mt5.model import (
    FIELD_LABELS,
    DataFolder,
    DiscoveryResult,
    EaInstallKind,
    Mt5Facts,
    OperationKind,
    TerminalEntry,
    TerminalsSnapshot,
    is_overdue,
)
from trading_os.launcher.report import COMPONENT_LABELS
from trading_os.shared.time import iso

HEALTH_URL = "GET /api/system/health"


class Family(StrEnum):
    ENVIRONMENT = "environment"
    COMPONENTS = "components"
    LAUNCHER = "launcher"
    CORE = "core"
    METATRADER = "metatrader"


class Severity(StrEnum):
    OK = "OK"
    INFO = "INFO"
    WARNING = "WARNING"
    PROBLEM = "PROBLEM"
    UNKNOWN = "UNKNOWN"


class Check(DomainModel):
    """One finding: what, where, how bad, why, and what to do. ``terminal_id`` and ``account_id`` are for the MetaTrader increments (ADR 0039)."""

    code: str
    family: Family
    severity: Severity
    subject: str
    detail: str
    remedy: str | None = None
    observed_at: datetime
    terminal_id: str | None = None
    account_id: str | None = None


class DoctorReport(DomainModel):
    observed_at: datetime
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return not self.count(Severity.PROBLEM)

    def count(self, severity: Severity) -> int:
        return sum(1 for check in self.checks if check.severity is severity)


class _Checks:
    """Collects the findings of one diagnosis, all stamped with the same observation time."""

    def __init__(self, at: datetime) -> None:
        self.at = at
        self.items: list[Check] = []

    def add(
        self,
        family: Family,
        severity: Severity,
        code: str,
        subject: str,
        detail: str,
        remedy: str | None = None,
    ) -> None:
        self.items.append(
            Check(
                code=code,
                family=family,
                severity=severity,
                subject=subject,
                detail=detail,
                remedy=remedy,
                observed_at=self.at,
            )
        )


# ------------------------------------------------------------------------------------------------ the diagnosis


def diagnose(
    observation: Observation, config: LauncherConfig, lock: LockInspection, mt5: Mt5Facts | None = None
) -> DoctorReport:
    checks = _Checks(observation.observed_at)
    _environment(checks, observation, config)
    _components(checks, observation, config)
    _launcher(checks, observation, lock)
    _core(checks, observation.core_health)
    _metatrader(checks, mt5, observation.observed_at)
    return DoctorReport(observed_at=observation.observed_at, checks=tuple(checks.items))


def _environment(checks: _Checks, observation: Observation, config: LauncherConfig) -> None:
    facts = observation.environment
    family = Family.ENVIRONMENT
    if facts.docker_available:
        checks.add(family, Severity.OK, "ENV_DOCKER_OK", "Docker", "Docker répond")
    else:
        checks.add(
            family,
            Severity.PROBLEM,
            "ENV_DOCKER_UNAVAILABLE",
            "Docker",
            "Docker Desktop ne répond pas",
            "démarrez Docker Desktop vous-même puis relancez le diagnostic ; le lanceur ne le démarre pas (ADR 0038, A11)",
        )
    if facts.venv_python_present:
        checks.add(
            family, Severity.OK, "ENV_VENV_OK", "Python", f"le Python du cœur est présent ({config.venv_python})"
        )
    else:
        checks.add(
            family,
            Severity.PROBLEM,
            "ENV_VENV_MISSING",
            "Python",
            f"le Python du cœur est absent ({config.venv_python})",
            'depuis 04_code\\python : py -3.14 -m venv .venv puis .venv\\Scripts\\python.exe -m pip install -e ".[dev]"',
        )
    if facts.env_file_present:
        checks.add(
            family, Severity.OK, "ENV_FILE_OK", ".env", ".env présent — son contenu n'est jamais lu par le lanceur"
        )
    else:
        checks.add(
            family,
            Severity.PROBLEM,
            "ENV_FILE_MISSING",
            ".env",
            ".env est absent",
            "lancez une fois scripts\\start.ps1 (il y écrit les jetons locaux, jamais affichés) ou copiez .env.example en .env",
        )
    if facts.npm_available:
        checks.add(family, Severity.OK, "ENV_NPM_OK", "npm", "npm est trouvé")
    else:
        checks.add(
            family,
            Severity.PROBLEM,
            "ENV_NPM_MISSING",
            "npm",
            "npm est introuvable",
            "installez Node.js : le cockpit ne peut pas démarrer sans lui",
        )


_UNHEALTHY_REMEDY = {
    Component.DATABASE: "lisez « docker logs {container} » puis décidez vous-même",
    Component.CORE: "lisez la fenêtre du cœur ou var/launcher/logs ; l'arrêter puis le relancer est votre geste (il retombe à OFF)",
    Component.COCKPIT: "lisez sa fenêtre ou var/launcher/logs ; après des 404 persistants, supprimez .next/dev puis relancez (runbook)",
}


def _components(checks: _Checks, observation: Observation, config: LauncherConfig) -> None:
    family = Family.COMPONENTS
    for item in observation.components:
        label = COMPONENT_LABELS[item.component]
        prefix = item.component.value.upper()
        _component_state(checks, item, label, prefix, config)
        _component_owner(checks, item, label, prefix)
        for warning in item.warnings:
            checks.add(
                family,
                Severity.WARNING,
                f"{prefix}_WARNING",
                label,
                warning,
                "corrigez comme indiqué ; le lanceur ne modifie rien",
            )


def _component_state(
    checks: _Checks, item: ComponentObservation, label: str, prefix: str, config: LauncherConfig
) -> None:
    family = Family.COMPONENTS
    state = item.state
    if state is ComponentState.HEALTHY:
        checks.add(family, Severity.OK, f"{prefix}_HEALTHY", label, item.detail or "répond")
    elif state is ComponentState.STARTING:
        checks.add(
            family,
            Severity.WARNING,
            f"{prefix}_STARTING",
            label,
            item.detail or "démarre encore",
            "attendez quelques secondes et relancez le diagnostic ; si cela dure, lisez les journaux (var/launcher/logs)",
        )
    elif state is ComponentState.UNHEALTHY:
        specific = _UNHEALTHY_REMEDY[item.component].format(container=config.container_name)
        checks.add(
            family,
            Severity.PROBLEM,
            f"{prefix}_UNHEALTHY",
            label,
            item.detail or "ne répond pas correctement",
            f"le lanceur ne relance jamais un composant malade : {specific}",
        )
    elif state is ComponentState.FOREIGN:
        checks.add(
            family,
            Severity.PROBLEM,
            f"{prefix}_PORT_FOREIGN",
            label,
            item.detail or "son port est tenu par un processus qui n'est pas de ce dépôt",
            "libérez le port vous-même ; le lanceur n'arrête jamais un processus qui n'est pas de ce dépôt",
        )
    elif state is ComponentState.UNAVAILABLE:
        checks.add(
            family,
            Severity.UNKNOWN,
            f"{prefix}_UNAVAILABLE",
            label,
            item.detail or "ne peut pas être observé",
        )
    else:  # ABSENT
        checks.add(
            family,
            Severity.INFO,
            f"{prefix}_ABSENT",
            label,
            "ne tourne pas",
            "le mode Infrastructure (« launcher start ») le démarre",
        )


def _component_owner(checks: _Checks, item: ComponentObservation, label: str, prefix: str) -> None:
    if item.state not in {ComponentState.HEALTHY, ComponentState.STARTING, ComponentState.UNHEALTHY}:
        return
    if item.ownership is Ownership.OWNED:
        checks.add(
            Family.COMPONENTS,
            Severity.OK,
            f"{prefix}_OWNED",
            label,
            "démarré par le lanceur : « stop » peut l'arrêter",
        )
    elif item.ownership is Ownership.RECOGNIZED and item.component is Component.DATABASE:
        # A container is never adopted (« la base est un conteneur, pas un processus »): advising it would advise what is refused.
        checks.add(
            Family.COMPONENTS,
            Severity.INFO,
            f"{prefix}_NOT_OWNED",
            label,
            "le conteneur est celui de ce dépôt, mais ce n'est pas le lanceur qui l'a démarré : « stop » ne l'arrêtera pas",
            "« launcher stop --include-database » l'arrêterait sur demande explicite, et jamais sous un cœur qui tourne ; "
            "un conteneur ne s'adopte pas",
        )
    elif item.ownership is Ownership.RECOGNIZED:
        checks.add(
            Family.COMPONENTS,
            Severity.INFO,
            f"{prefix}_NOT_OWNED",
            label,
            "de ce dépôt, mais lancé à la main : « stop » ne l'arrêtera pas",
            f"« launcher adopt {item.component.value} » si vous voulez que le lanceur puisse l'arrêter "
            "(l'arrêt poli est tenté d'abord ; si le processus ne le prend pas, l'arrêt est forcé et le rapport le dit)",
        )


def _launcher(checks: _Checks, observation: Observation, lock: LockInspection) -> None:
    family = Family.LAUNCHER
    subject = "lanceur"
    if observation.registry_problem:
        checks.add(
            family,
            Severity.WARNING,
            "LAUNCHER_REGISTRY_UNREADABLE",
            subject,
            f"registre des processus illisible : {observation.registry_problem} — il n'est pas utilisé",
            "le lanceur ne connaît donc aucun processus possédé : refaites « launcher adopt » pour ce qui tourne ; "
            "le fichier illisible est alors mis de côté (state.json.corrupt-…), jamais écrasé",
        )
    if lock.state is LockState.FREE:
        checks.add(family, Severity.OK, "LAUNCHER_LOCK_FREE", subject, "aucun autre lanceur ne tourne")
    elif lock.state is LockState.HELD:
        checks.add(family, Severity.INFO, "LAUNCHER_BUSY", subject, f"un autre lanceur tourne (pid {lock.pid})")
    else:
        owner = f" (pid {lock.pid})" if lock.pid is not None else ""
        checks.add(
            family,
            Severity.WARNING,
            "LAUNCHER_LOCK_STALE",
            subject,
            f"le verrou du lanceur est périmé : son propriétaire{owner} n'existe plus",
            "rien à faire : le prochain démarrage ou arrêt le remplace seul ; le diagnostic ne touche à rien",
        )
    if observation.owned:
        count = len(observation.owned)
        checks.add(
            family,
            Severity.INFO,
            "LAUNCHER_OWNED_PROCESSES",
            subject,
            f"{count} processus possédé(s) par le lanceur : « stop » les arrêterait",
        )
    else:
        checks.add(
            family,
            Severity.INFO,
            "LAUNCHER_NOTHING_OWNED",
            subject,
            "le lanceur ne possède aucun processus : « stop » n'arrêterait rien",
        )


def _core(checks: _Checks, health: CoreHealth | None) -> None:
    family = Family.CORE
    subject = "cœur"
    if health is None:
        checks.add(
            family,
            Severity.UNKNOWN,
            "CORE_VIEW_UNAVAILABLE",
            subject,
            "le cœur ne répond pas : rien à lire de sa santé",
        )
        return
    where = f"voir {HEALTH_URL} ou l'écran Démarrage du cockpit"
    if health.status == "ok":
        checks.add(family, Severity.OK, "CORE_STATUS_OK", subject, f"version {health.version}, statut ok")
    elif health.status == "critical":
        checks.add(
            family, Severity.PROBLEM, "CORE_STATUS_CRITICAL", subject, "le cœur se déclare en état critique", where
        )
    else:
        checks.add(
            family, Severity.WARNING, "CORE_STATUS_DEGRADED", subject, f"statut du cœur : « {health.status} »", where
        )
    if not health.database_up:
        checks.add(
            family,
            Severity.PROBLEM,
            "CORE_DATABASE_DOWN",
            subject,
            "le cœur dit que sa base est injoignable",
            "vérifiez le conteneur de la base (ligne « base » ci-dessus) ; le lanceur ne redémarre pas un cœur en marche",
        )
    if health.findings:
        checks.add(
            family,
            Severity.WARNING,
            "CORE_FINDINGS",
            subject,
            f"{health.findings} signalement(s) du cœur",
            f"lisez le champ findings de {HEALTH_URL}",
        )
    _agents(checks, health)
    _workers(checks, health)
    if health.execution_mode is not None:
        checks.add(family, Severity.INFO, "CORE_EXECUTION_MODE", subject, f"mode d'exécution : {health.execution_mode}")


def _agents(checks: _Checks, health: CoreHealth) -> None:
    family, subject = Family.CORE, "agents EA"
    if health.agents_connected is None:
        checks.add(
            family,
            Severity.INFO,
            "CORE_AGENTS_UNREPORTED",
            subject,
            "le cœur ne dit pas combien d'agents sont connectés",
        )
    elif health.agents_connected == 0:
        checks.add(
            family,
            Severity.INFO,
            "CORE_NO_AGENT",
            subject,
            "aucun agent EA connecté (normal tant que l'EA n'est pas attaché à un graphique)",
        )
    else:
        checks.add(
            family, Severity.OK, "CORE_AGENT_CONNECTED", subject, f"{health.agents_connected} agent(s) EA connecté(s)"
        )


def _workers(checks: _Checks, health: CoreHealth) -> None:
    family, subject = Family.CORE, "workers MT5"
    workers = health.mt5_workers
    if workers is None:
        checks.add(family, Severity.INFO, "MT5_WORKERS_UNREPORTED", subject, "le cœur ne rapporte pas ses workers MT5")
    elif workers.alive == 0:
        checks.add(
            family,
            Severity.INFO,
            "MT5_NO_ACCOUNT",
            subject,
            f"aucun compte rattaché (0 worker vivant ; {workers.spawned} lancé(s), {workers.ended} terminé(s))",
        )
    elif workers.alive == 1:
        checks.add(
            family,
            Severity.OK,
            "MT5_WORKERS_OK",
            subject,
            f"un worker vivant, comme un seul compte rattaché ({workers.spawned} lancé(s), {workers.ended} terminé(s))",
        )
    else:
        checks.add(
            family,
            Severity.WARNING,
            "MT5_WORKERS_EXCESS",
            subject,
            f"{workers.alive} workers vivants alors qu'un seul compte est rattaché à la fois (ADR 0021, 0037)",
            f"ne tuez aucun processus à la main : lisez {HEALTH_URL} et les incidents du superviseur, puis signalez-le",
        )


def _metatrader(checks: _Checks, mt5: Mt5Facts | None, now: datetime) -> None:
    family = Family.METATRADER
    if mt5 is None:
        checks.add(
            family,
            Severity.UNKNOWN,
            "MT5_NOT_INSPECTED",
            "MetaTrader 5",
            "ce diagnostic ne regarde pas MetaTrader 5, l'agent EA, le preset ni le graphique ; "
            "seuls les agents connectés au cœur sont visibles (voir « Cœur »)",
        )
        return
    snapshot = mt5.snapshot
    if snapshot.problem:
        checks.add(
            family,
            Severity.WARNING,
            "MT5_REGISTRY_UNREADABLE",
            "terminaux",
            f"{snapshot.problem} — aucun terminal n'est tenu pour enregistré",
            "le fichier illisible est mis de côté (terminals.json.corrupt-…) au prochain enregistrement : "
            "réenregistrez vos terminaux avec « launcher mt5 register »",
        )
    if mt5.discovery is None:
        checks.add(
            family,
            Severity.UNKNOWN,
            "MT5_DISCOVERY_FAILED",
            "MetaTrader 5",
            f"la recherche des terminaux a échoué : {mt5.error or 'raison inconnue'}",
        )
    else:
        _mt5_found(checks, mt5.discovery, snapshot)
    _mt5_registered(checks, mt5, now)
    if snapshot.terminals:
        checks.add(
            family,
            Severity.INFO,
            "MT5_EA_STATE_BY_STATUS",
            "MetaTrader 5",
            "le déploiement et le preset de chaque terminal enregistré sont contrôlés ci-dessus ; l'état courant de l'attachement (processus, hello, "
            "lecture du cœur) se lit avec « launcher mt5 status » : ce diagnostic ne regarde ni les processus des terminaux ni les conditions du cœur",
        )
    else:
        checks.add(
            family,
            Severity.UNKNOWN,
            "MT5_EA_STATE_NOT_INSPECTED",
            "MetaTrader 5",
            "aucun terminal n'est enregistré : l'état d'un agent (déployé, préparé, attaché, connecté) ne s'inspecte que pour un terminal enregistré "
            "(« launcher mt5 register », puis « launcher mt5 status ») ; seuls les agents connectés au cœur sont visibles (voir « Cœur »)",
        )


def _mt5_found(checks: _Checks, discovery: DiscoveryResult, snapshot: TerminalsSnapshot) -> None:
    family = Family.METATRADER
    registered = {entry.terminal_id: entry for entry in snapshot.terminals}
    if not discovery.installations:
        checks.add(
            family,
            Severity.WARNING,
            "MT5_NONE_FOUND",
            "MetaTrader 5",
            "aucune installation de MetaTrader 5 détectée",
            "si un terminal existe, enregistrez-le à la main : launcher mt5 register --install-path <dossier d'installation du terminal> "
            "--data-path <dossier de données> (ou --portable)",
        )
    for rejected in discovery.rejected:
        checks.add(
            family,
            Severity.WARNING,
            "MT5_CANDIDATE_REJECTED",
            "MetaTrader 5",
            f"{rejected.path} : {rejected.reason}",
            "vérifiez ou corrigez ce chemin ; le lanceur n'y touche pas",
        )
    for path in discovery.unmatched_data_folders:
        checks.add(
            family,
            Severity.INFO,
            "MT5_UNMATCHED_DATA_FOLDER",
            "MetaTrader 5",
            f"dossier de données sans installation trouvée : {path}",
        )
    count = 0
    for installation in discovery.installations:
        version = f" (version {installation.version})" if installation.version else ""
        if installation.running:
            state = "en cours (" + ", ".join(f"pid {item.pid}" for item in installation.running) + ")"
        else:
            state = "arrêtée"
        checks.add(
            family,
            Severity.INFO,
            "MT5_INSTALLATION_FOUND",
            "MetaTrader 5",
            f"installation {installation.install_path}{version}, {state}",
        )
        for folder in installation.data_folders:
            count += 1
            _mt5_data_folder(checks, folder, registered.get(folder.terminal_id))
    if count > 1:
        checks.add(
            family,
            Severity.INFO,
            "MT5_SEVERAL_TERMINALS",
            "MetaTrader 5",
            f"{count} terminaux détectés : aucune sélection automatique, le choix se fait avec --terminal <identifiant>",
        )


def _mt5_data_folder(checks: _Checks, folder: DataFolder, entry: TerminalEntry | None) -> None:
    family = Family.METATRADER
    subject = f"terminal {folder.terminal_id[:8]}"
    if not folder.eas:
        reason = (
            "dossier MQL5\\Experts absent"
            if not folder.experts_present
            else "notre agent n'est pas installé dans MQL5\\Experts"
        )
        checks.add(family, Severity.INFO, "MT5_EA_NOT_INSTALLED", subject, f"{folder.terminal_id} : {reason}")
    for ea in folder.eas:
        if ea.kind is EaInstallKind.JUNCTION:
            checks.add(
                family,
                Severity.INFO,
                "MT5_EA_AGENT_JUNCTION",
                subject,
                f"{folder.terminal_id} : notre agent est installé par jonction {ea.name} → {ea.target or '(cible illisible)'} "
                "(respectée, jamais supprimée)",
            )
        else:
            checks.add(
                family,
                Severity.INFO,
                "MT5_EA_AGENT_DIRECTORY",
                subject,
                f"{folder.terminal_id} : notre agent est installé dans le dossier {ea.name}",
            )
    if not folder.presets_present:
        checks.add(
            family,
            Severity.INFO,
            "MT5_PRESETS_FOLDER_MISSING",
            subject,
            f"{folder.terminal_id} : le dossier MQL5\\Presets n'existe pas (il sera créé quand le preset sera écrit, incrément I5)",
        )
    if not folder.link_file_present:
        checks.add(
            family,
            Severity.INFO,
            "MT5_LINK_FILE_MISSING",
            subject,
            f"{folder.terminal_id} : le fichier de liaison de l'agent est absent de MQL5\\Files "
            "(écrit au déploiement ; son contenu n'est jamais lu)",
        )
    if folder.third_party_experts:
        checks.add(
            family,
            Severity.INFO,
            "MT5_THIRD_PARTY_EXPERTS",
            subject,
            f"{folder.terminal_id} : EA tiers installés (compilés), pas forcément attachés : "
            + ", ".join(folder.third_party_experts),
        )
    if entry is None:
        checks.add(
            family,
            Severity.INFO,
            "MT5_TERMINAL_UNREGISTERED",
            subject,
            f"{folder.terminal_id} : terminal non enregistré",
            f"launcher mt5 register --terminal {folder.terminal_id}",
        )


def _mt5_registered(checks: _Checks, mt5: Mt5Facts, now: datetime) -> None:
    family = Family.METATRADER
    found = (
        {folder.terminal_id for installation in mt5.discovery.installations for folder in installation.data_folders}
        if mt5.discovery is not None
        else None
    )
    for entry in mt5.snapshot.terminals:
        subject = f"terminal {entry.terminal_id[:8]}"
        if found is not None and entry.terminal_id not in found:
            checks.add(
                family,
                Severity.WARNING,
                "MT5_TERMINAL_NOT_FOUND",
                subject,
                f"le terminal enregistré « {entry.label} » ({entry.terminal_id}) est introuvable à {entry.data_path}",
                "vérifiez que le terminal et son dossier de données existent encore ; le registre n'est pas modifié "
                "(rien n'est supprimé)",
            )
        elif found is not None:
            missing = entry.declared.missing_fields()
            if missing:
                checks.add(
                    family,
                    Severity.INFO,
                    "MT5_DECLARATION_INCOMPLETE",
                    subject,
                    f"{entry.label} : déclaration incomplète — manque : "
                    + ", ".join(FIELD_LABELS[name] for name in missing),
                    f"launcher mt5 register --terminal {entry.terminal_id} …",
                )
            else:
                checks.add(
                    family,
                    Severity.OK,
                    "MT5_TERMINAL_REGISTERED",
                    subject,
                    f"{entry.label} : enregistré, déclaration complète",
                )
        operation = entry.operation
        if is_overdue(operation, now):
            checks.add(
                family,
                Severity.PROBLEM,
                "MT5_OPERATION_OVERDUE",
                subject,
                f"{entry.label} : l'opération {operation.kind.value} ({operation.deployment_id}, étape « {operation.step} ») "
                "a dépassé son échéance — état LAUNCHER_OPERATION_INTERRUPTED, elle n'est jamais reprise en silence",
                "lisez les journaux du lanceur (var/launcher) et vérifiez l'état réel du terminal à la main ; "
                "la commande qui libère une opération interrompue arrive avec le déploiement (incrément I4)",
            )
        elif operation.kind is not OperationKind.IDLE:
            checks.add(
                family,
                Severity.INFO,
                "MT5_OPERATION_IN_PROGRESS",
                subject,
                f"{entry.label} : {operation.kind.value} en cours ({operation.deployment_id}, étape « {operation.step} »)",
            )


# ------------------------------------------------------------------------------------------------ the report

FAMILY_TITLES = {
    Family.ENVIRONMENT: "Environnement",
    Family.COMPONENTS: "Composants",
    Family.LAUNCHER: "Lanceur",
    Family.CORE: "Cœur",
    Family.METATRADER: "MetaTrader 5",
}
SEVERITY_LABELS = {
    Severity.OK: "OK",
    Severity.INFO: "info",
    Severity.WARNING: "ATTENTION",
    Severity.PROBLEM: "PROBLÈME",
    Severity.UNKNOWN: "?",
}


def render_doctor(report: DoctorReport) -> str:
    lines = [
        f"Diagnostic Trading OS — {iso(report.observed_at)} (lecture seule : rien n'est modifié, rien n'est lancé)",
        "",
    ]
    for family in Family:
        group = [check for check in report.checks if check.family is family]
        if not group:
            continue
        lines.append(FAMILY_TITLES[family])
        for check in group:
            lines.append(f"  [{SEVERITY_LABELS[check.severity]:<9}] {check.subject:<12} {check.detail}")
            if check.remedy:
                lines.append(f"      → action : {check.remedy}")
        lines.append("")
    problems, warnings = report.count(Severity.PROBLEM), report.count(Severity.WARNING)
    unknown = report.count(Severity.UNKNOWN)
    if problems:
        summary = f"Résultat : {problems} problème(s), {warnings} avertissement(s)"
    else:
        summary = f"Résultat : aucun problème détecté, {warnings} avertissement(s)"
    if unknown:
        summary += f", {unknown} point(s) non évaluable(s)"
    lines.append(summary + ".")
    return "\n".join(lines)


def doctor_document(report: DoctorReport) -> dict[str, Any]:
    return {
        **report.model_dump(mode="json", by_alias=True),
        "ok": report.ok,
        "problems": report.count(Severity.PROBLEM),
        "warnings": report.count(Severity.WARNING),
    }
