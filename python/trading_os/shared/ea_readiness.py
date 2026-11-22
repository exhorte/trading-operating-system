"""Is the agent of a terminal technically ready? (ADR 0039 § 5 and § 9) — one pure function, a *reading* of fourteen conditions.

``BLOCKED`` if any is red (the situation forbids it, with the exact codes), ``VALIDATING`` if none is red and any is pending (not yet known: a heartbeat not yet
fresh, a reconciliation not yet done since this attachment), ``READY`` if all are green. It is **technical**. Whether an order may be placed is another line,
``Execution Authorization``, with its own reasons — a terminal can be ``READY`` while the authorization is ``BLOCKED — SYSTEM_MODE_OFF``.

It decides nothing: it raises no mode, writes nothing, sends nothing. It is a precondition reading and only ever tightens: a preparation that used to pass
without a declaration now asks for one (C6, option b). It lives in ``shared`` so that the core (which has the facts) serves the verdict and the launcher
(which prepares and observes) shows it, without either importing the other.

Product identity (C6): a product deduced from an *observed* signal — the symbol suffix — is green only if Exhorte declared the same one, with the warning
``PRODUCT_UNCONFIRMED``; it is never shown as confirmed. ``ACCOUNT_IDENTITY_UNVERIFIED`` heads the red lines of the identity and of the product.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from trading_os.shared.agent_compat import CompatResult, assess_agent

HEARTBEAT_FRESH_S = 15.0  # the core's AGENT_FRESH
HEARTBEAT_STALE_S = 30.0  # the dead-man window of the agent and the watchdog of the core
HEADER_IDENTITY = "ACCOUNT_IDENTITY_UNVERIFIED"

_PRODUCT_BLOCKERS = frozenset(
    {
        "account_facts_missing",
        "provider_not_identified",
        "provider_ambiguous",
        "provider_mismatch",
        "environment_mismatch",
        "account_product_unknown",
    }
)
_MODES_THAT_BLOCK = ("OFF", "OBSERVE")


class Light(StrEnum):
    GREEN = "GREEN"
    RED = "RED"
    PENDING = "PENDING"


@dataclass(frozen=True)
class ReadinessInput:
    """Everything the reading is given. ``None`` is « not known » — never an invented value, and never green."""

    # what Exhorte declared about the terminal (registry)
    declared_login: str | None = None
    declared_provider: str | None = None
    declared_product: str | None = None
    declared_symbols: tuple[str, ...] = ()
    declared_chart_symbol: str | None = None
    # the terminal and the core
    terminal_running: bool | None = None
    mt5_connected: bool | None = None
    core_ok: bool | None = None
    readiness_checks: dict[str, bool | None] = field(default_factory=dict)
    execution_mode: str | None = None
    # the account's identification (core)
    broker_product: str | None = None
    product_observed: bool = (
        False  # the product is deduced from an observed signal (the symbol suffix), not from a declared contract
    )
    identification_blockers: tuple[str, ...] = ()
    identification_executable: bool | None = None
    # the agent (its hello and heartbeat, as the core holds them)
    hello_received: bool = False
    agent_version: str | None = None
    capabilities: tuple[str, ...] | None = None
    protocol_version: int | None = None
    agent_login: str | None = None
    identity: str | None = None
    heartbeat_age_s: float | None = None
    core_silent_ms: int | None = None
    attached_experts: tuple[str, ...] | None = None  # every OTHER expert in the terminal
    agent_compiled_mode: str | None = None
    halted: bool | None = None
    tradable: bool | None = None
    reported_chart: tuple[str, str] | None = None  # 1.14: symbol and period of the chart the agent is on
    reported_params_match: bool | None = None  # 1.14: the agent's inputs are the preset's; None = not reported
    init_state: str | None = None  # 1.14: READY / DEGRADED
    init_issues: tuple[str, ...] = ()
    instance_id: str | None = None  # 1.14: the data folder's own name, as the agent reports it
    terminal_id: str | None = (
        None  # the registered terminal's identifier, when it is the name of a data folder (not for a portable one)
    )
    # the attachment
    attach_reconciled: bool | None = None  # a reconciliation succeeded after this agent registered
    unresolved_commands: int | None = None


@dataclass(frozen=True)
class Condition:
    code: str
    label: str
    light: Light
    detail: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionAuthorization:
    allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EaReadiness:
    verdict: str  # READY / VALIDATING / BLOCKED
    conditions: tuple[Condition, ...]
    red_codes: tuple[str, ...]
    pending_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    header_code: str | None
    execution_authorization: ExecutionAuthorization


def _green(code: str, label: str, detail: str) -> Condition:
    return Condition(code, label, Light.GREEN, detail)


def _red(code: str, label: str, detail: str, *reasons: str) -> Condition:
    return Condition(code, label, Light.RED, detail, reasons)


def _pending(code: str, label: str, detail: str, *reasons: str) -> Condition:
    return Condition(code, label, Light.PENDING, detail, reasons)


def evaluate_ea_readiness(facts: ReadinessInput) -> EaReadiness:
    warnings: list[str] = []
    conditions = [
        _terminal(facts),
        _broker(facts),
        _identity(facts),
        _product(facts, warnings),
        _loaded(facts),
        *_agent_conditions(facts, warnings),
        _core(facts),
        _account_not_blocked(facts),
    ]
    red = tuple(dict.fromkeys(code for item in conditions if item.light is Light.RED for code in item.reason_codes))
    pending = tuple(
        dict.fromkeys(code for item in conditions if item.light is Light.PENDING for code in item.reason_codes)
    )
    verdict = "BLOCKED" if red else "VALIDATING" if pending else "READY"
    header = (
        HEADER_IDENTITY
        if any(item.light is Light.RED and item.code in {"ACCOUNT_IDENTITY", "PRODUCT_IDENTITY"} for item in conditions)
        else None
    )
    return EaReadiness(
        verdict=verdict,
        conditions=tuple(conditions),
        red_codes=red,
        pending_codes=pending,
        warning_codes=tuple(dict.fromkeys(warnings)),
        header_code=header,
        execution_authorization=_authorization(facts, verdict),
    )


# ------------------------------------------------------------------------------------------------ the conditions


def _terminal(f: ReadinessInput) -> Condition:
    label = "Terminal MetaTrader démarré"
    if f.terminal_running is None:
        return _pending("TERMINAL_RUNNING", label, "on ne sait pas si le terminal tourne", "TERMINAL_STATE_UNKNOWN")
    if not f.terminal_running:
        return _red("TERMINAL_RUNNING", label, "le terminal ne tourne pas", "TERMINAL_NOT_RUNNING")
    return _green("TERMINAL_RUNNING", label, "le terminal tourne")


def _broker(f: ReadinessInput) -> Condition:
    label = "Connexion au courtier"
    if f.mt5_connected is None:
        return _pending(
            "BROKER_CONNECTION", label, "le cœur ne dit pas si le courtier est joint", "BROKER_CONNECTION_UNKNOWN"
        )
    if not f.mt5_connected:
        return _red("BROKER_CONNECTION", label, "le terminal n'est pas connecté au courtier", "BROKER_NOT_CONNECTED")
    return _green("BROKER_CONNECTION", label, "le terminal est connecté au courtier")


def _identity(f: ReadinessInput) -> Condition:
    label = "Compte identifié"
    reasons: list[str] = []
    if f.hello_received:
        if f.declared_login is None:
            reasons.append("LOGIN_UNDECLARED")
        elif f.agent_login != f.declared_login or f.identity == "mismatch" or f.identity not in (None, "ok"):
            reasons.append("MT5_ACCOUNT_MISMATCH")
    others = [b for b in f.identification_blockers if b not in _PRODUCT_BLOCKERS]
    reasons.extend(others)
    if f.identification_executable is False and not f.identification_blockers:
        reasons.append("ACCOUNT_NOT_EXECUTABLE")
    if reasons:
        return _red(
            "ACCOUNT_IDENTITY",
            label,
            "le compte ne correspond pas à ce qui est déclaré ou n'est pas exécutable : " + ", ".join(reasons),
            *reasons,
        )
    if f.identification_executable is None or (f.hello_received and f.identity is None):
        return _pending(
            "ACCOUNT_IDENTITY", label, "l'identification du compte n'est pas encore connue", "IDENTIFICATION_UNKNOWN"
        )
    return _green(
        "ACCOUNT_IDENTITY",
        label,
        f"login {f.agent_login or f.declared_login} conforme à la déclaration, identification exécutable",
    )


def _product(f: ReadinessInput, warnings: list[str]) -> Condition:
    label = "Identité du produit"
    blockers = [b for b in f.identification_blockers if b in _PRODUCT_BLOCKERS]
    if blockers:
        return _red("PRODUCT_IDENTITY", label, "l'identification du compte bloque : " + ", ".join(blockers), *blockers)
    product = (f.broker_product or "").upper()
    if not product or product == "UNKNOWN":
        return _red("PRODUCT_IDENTITY", label, "le produit du compte n'est pas identifié", "PRODUCT_UNKNOWN")
    if not f.product_observed:
        return _green("PRODUCT_IDENTITY", label, f"{product}, d'après le contrat déclaré au cœur (ADR 0036)")
    declared = (f.declared_product or "").upper()
    if not declared:
        return _red(
            "PRODUCT_IDENTITY",
            label,
            f"{product} est déduit du seul suffixe des symboles, et aucun produit n'est déclaré pour ce terminal",
            "PRODUCT_UNDECLARED",
        )
    if declared != product:
        return _red(
            "PRODUCT_IDENTITY",
            label,
            f"le produit déduit est {product}, le produit déclaré est {declared}",
            "PRODUCT_MISMATCH",
        )
    warnings.append("PRODUCT_UNCONFIRMED")
    return _green(
        "PRODUCT_IDENTITY",
        label,
        f"{product} déduit du suffixe et déclaré à l'identique — jamais « confirmé » : un suffixe seul ne prouve rien",
    )


def _loaded(f: ReadinessInput) -> Condition:
    label = "Agent chargé"
    if f.hello_received:
        if f.init_state == "DEGRADED":
            issues = ", ".join(f.init_issues) or "motifs non donnés"
            return _red("EA_LOADED", label, f"l'agent s'est initialisé en mode dégradé : {issues}", "EA_INIT_DEGRADED")
        if f.instance_id and f.terminal_id and f.instance_id.lower() != f.terminal_id.lower():
            return _red(
                "EA_LOADED",
                label,
                f"le hello vient du dossier de données {f.instance_id}, le terminal enregistré est {f.terminal_id}",
                "MT5_INSTANCE_MISMATCH",
            )
        return _green("EA_LOADED", label, "le cœur a reçu le hello de l'agent")
    return _pending("EA_LOADED", label, "aucun hello de l'agent n'est encore arrivé au cœur", "NO_HELLO")


def _agent_conditions(f: ReadinessInput, warnings: list[str]) -> list[Condition]:
    if not f.hello_received:
        names = (
            ("VERSION_COMPATIBLE", "Version et protocole compatibles"),
            ("SYMBOL_AND_CHART", "Symbole et graphique conformes"),
            ("PARAMETERS", "Paramètres conformes au preset"),
            ("HEARTBEAT_FRESH", "Battement frais"),
            ("LOCAL_PROTECTIONS", "Protections locales annoncées"),
            ("NO_THIRD_PARTY_EA", "Aucun autre EA attaché"),
            ("RECONCILED", "Réconciliation faite depuis l'attachement"),
        )
        return [_pending(code, label, "en attente du hello de l'agent", "NO_HELLO") for code, label in names]
    return [
        _version(f, warnings),
        _symbol(f, warnings),
        _parameters(f, warnings),
        _heartbeat(f),
        _protections(f, warnings),
        _third_party(f),
        _reconciled(f),
    ]


def _version(f: ReadinessInput, warnings: list[str]) -> Condition:
    label = "Version et protocole compatibles"
    compat = assess_agent(f.agent_version, f.capabilities, f.protocol_version)
    warnings.extend(code for code in compat.codes if code != "CAPABILITY_DEAD_MAN_MISSING" and compat.compatible)
    if compat.result is CompatResult.INCOMPATIBLE:
        return _red("VERSION_COMPATIBLE", label, "; ".join(compat.reasons), "EA_PROTOCOL_INCOMPATIBLE", *compat.codes)
    return _green("VERSION_COMPATIBLE", label, f"agent {f.agent_version} accepté par la table de compatibilité")


def _symbol(f: ReadinessInput, warnings: list[str]) -> Condition:
    label = "Symbole et graphique conformes"
    if not f.declared_chart_symbol or not f.declared_symbols:
        return _red(
            "SYMBOL_AND_CHART",
            label,
            "le graphique ou les symboles autorisés ne sont pas déclarés",
            "SYMBOL_UNDECLARED",
        )
    if f.declared_chart_symbol not in f.declared_symbols:
        return _red(
            "SYMBOL_AND_CHART",
            label,
            f"{f.declared_chart_symbol} n'est pas dans la liste des symboles autorisés",
            "SYMBOL_NOT_ALLOWED",
        )
    if f.reported_chart is None:
        warnings.append("CHART_UNVERIFIED")
        return _green(
            "SYMBOL_AND_CHART",
            label,
            "symbole déclaré autorisé ; le graphique réel n'est pas rapporté par cette version de l'agent",
        )
    if f.reported_chart[0] != f.declared_chart_symbol:
        return _red(
            "SYMBOL_AND_CHART",
            label,
            f"l'agent est sur {f.reported_chart[0]}, le graphique déclaré est {f.declared_chart_symbol}",
            "CHART_MISMATCH",
        )
    return _green(
        "SYMBOL_AND_CHART", label, f"l'agent est sur {f.reported_chart[0]} {f.reported_chart[1]}, comme déclaré"
    )


def _parameters(f: ReadinessInput, warnings: list[str]) -> Condition:
    label = "Paramètres conformes au preset"
    if f.reported_params_match is False:
        return _red("PARAMETERS", label, "les paramètres de l'agent ne sont pas ceux du preset", "PARAMETERS_MISMATCH")
    if f.reported_params_match is None:
        warnings.append("PARAMETERS_UNREPORTED")
        return _green("PARAMETERS", label, "cette version de l'agent ne rapporte pas ses paramètres : non vérifiable")
    return _green("PARAMETERS", label, "les paramètres de l'agent sont ceux du preset")


def _heartbeat(f: ReadinessInput) -> Condition:
    label = "Battement frais"
    age = f.heartbeat_age_s
    if age is None:
        return _pending("HEARTBEAT_FRESH", label, "aucun battement reçu pour l'instant", "HEARTBEAT_NOT_YET")
    if age >= HEARTBEAT_STALE_S:
        return _red(
            "HEARTBEAT_FRESH",
            label,
            f"dernier battement il y a {age:.0f} s (seuil de péremption {HEARTBEAT_STALE_S:g} s)",
            "HEARTBEAT_STALE",
        )
    if age >= HEARTBEAT_FRESH_S:
        return _pending(
            "HEARTBEAT_FRESH",
            label,
            f"dernier battement il y a {age:.0f} s (frais sous {HEARTBEAT_FRESH_S:g} s)",
            "HEARTBEAT_SLOW",
        )
    return _green("HEARTBEAT_FRESH", label, f"dernier battement il y a {age:.0f} s")


def _protections(f: ReadinessInput, warnings: list[str]) -> Condition:
    label = "Protections locales annoncées"
    if f.capabilities is None:
        return _pending("LOCAL_PROTECTIONS", label, "l'agent ne rapporte pas ses capacités", "CAPABILITIES_UNREPORTED")
    if "dead_man" not in f.capabilities:
        return _red(
            "LOCAL_PROTECTIONS", label, "l'agent n'annonce pas la capacité dead_man", "LOCAL_PROTECTIONS_MISSING"
        )
    if f.core_silent_ms is None:
        return _pending(
            "LOCAL_PROTECTIONS", label, "aucun ping du cœur n'a encore été reçu par l'agent", "PING_NOT_YET_RECEIVED"
        )
    warnings.append("LOCAL_PROTECTIONS_ANNOUNCED_ONLY")
    return _green(
        "LOCAL_PROTECTIONS",
        label,
        "dead_man annoncé et ping reçu — « fonctionnel » ne se prouve qu'avec un ordre, ce que ce lecteur ne fait jamais",
    )


def _third_party(f: ReadinessInput) -> Condition:
    label = "Aucun autre EA attaché"
    if f.attached_experts is None:
        return _pending(
            "NO_THIRD_PARTY_EA", label, "l'agent ne rapporte pas les autres experts du terminal", "EXPERTS_UNREPORTED"
        )
    if f.attached_experts:
        return _red(
            "NO_THIRD_PARTY_EA",
            label,
            "un autre EA est attaché : " + ", ".join(f.attached_experts),
            "THIRD_PARTY_EA_ATTACHED",
        )
    return _green("NO_THIRD_PARTY_EA", label, "aucun autre expert dans le terminal")


def _reconciled(f: ReadinessInput) -> Condition:
    label = "Réconciliation faite depuis l'attachement"
    if f.unresolved_commands:
        return _red(
            "RECONCILED",
            label,
            f"{f.unresolved_commands} commande(s) non résolue(s) : jamais rejouées, seule la réconciliation les ferme",
            "UNRESOLVED_COMMANDS",
        )
    if f.attach_reconciled is None or f.unresolved_commands is None:
        return _pending("RECONCILED", label, "l'état de la réconciliation n'est pas connu", "RECONCILIATION_PENDING")
    if not f.attach_reconciled:
        return _pending(
            "RECONCILED",
            label,
            "aucune réconciliation n'a réussi depuis l'attachement de cet agent",
            "RECONCILIATION_PENDING",
        )
    return _green("RECONCILED", label, "une réconciliation a réussi depuis l'attachement, aucune commande en doute")


def _core(f: ReadinessInput) -> Condition:
    label = "Cœur et Risk Engine opérationnels"
    if f.core_ok is None:
        return _pending("CORE_AND_RISK", label, "l'état du cœur n'est pas connu", "CORE_STATUS_UNKNOWN")
    if not f.core_ok:
        return _red("CORE_AND_RISK", label, "le cœur signale un problème", "CORE_NOT_OK")
    return _green("CORE_AND_RISK", label, "le cœur est en bonne santé")


def _account_not_blocked(f: ReadinessInput) -> Condition:
    label = "Compte non bloqué"
    incident = f.readiness_checks.get("no_critical_incident")
    limits = f.readiness_checks.get("account_limits_configured")
    reasons = [
        code
        for check, code in ((incident, "CRITICAL_INCIDENT"), (limits, "ACCOUNT_LIMITS_NOT_CONFIGURED"))
        if check is False
    ]
    if reasons:
        return _red("ACCOUNT_NOT_BLOCKED", label, "le compte est bloqué : " + ", ".join(reasons), *reasons)
    if incident is None or limits is None:
        return _pending(
            "ACCOUNT_NOT_BLOCKED", label, "le cœur ne dit pas si le compte est bloqué", "ACCOUNT_STATE_UNKNOWN"
        )
    return _green("ACCOUNT_NOT_BLOCKED", label, "aucun incident critique, limites du compte écrites")


# ------------------------------------------------------------------------------------------------ the authorization (a separate line)


def _authorization(f: ReadinessInput, verdict: str) -> ExecutionAuthorization:
    reasons: list[str] = []
    mode = (f.execution_mode or "").upper()
    if not mode:
        reasons.append("SYSTEM_MODE_UNKNOWN")
    elif mode in _MODES_THAT_BLOCK:
        reasons.append(f"SYSTEM_MODE_{mode}")
    elif mode == "HALTED":
        reasons.append("HALTED")
    compiled = (f.agent_compiled_mode or "").upper()
    if not compiled:
        reasons.append("AGENT_MODE_UNKNOWN")
    elif compiled == "OBSERVE":
        reasons.append("AGENT_COMPILED_OBSERVE")
    if f.halted:
        reasons.append("HALTED")
    if not f.tradable:
        reasons.append("ACCOUNT_NOT_TRADABLE")
    if verdict != "READY":
        reasons.append("NOT_READY")
    unique = tuple(dict.fromkeys(reasons))
    return ExecutionAuthorization(allowed=not unique, reasons=unique)
