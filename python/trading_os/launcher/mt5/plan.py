"""``launcher mt5 plan`` (ADR 0039, I3): what the preparation of MetaTrader 5 would do next, from what is found and what is registered.

A pure function and its text. It chooses nothing for the user (several terminals are listed, never picked), it says plainly which steps do not exist
yet (deployment, preset, start, attachment check — increments I4 to I7), and it never says a terminal or the EA is ready.
"""

from __future__ import annotations

from typing import Any

from trading_os.launcher.mt5.model import (
    FIELD_LABELS,
    DataFolder,
    DiscoveryResult,
    EaInstallKind,
    Installation,
    Mt5Plan,
    PlanStatus,
    TerminalEntry,
    TerminalPlan,
    TerminalsSnapshot,
)
from trading_os.shared.time import iso

FLAGS = {
    "account_id": "--account-id <compte>",
    "expected_login": "--expected-login <login>",
    "chart": "--symbol <symbole> --period <période>",
    "magic": "--magic <numéro>",
    "allowed_symbols": "--allowed-symbols <a,b>",
    "provider": "--provider <FOURNISSEUR>",
    "product": "--product <PRODUIT>",
}
NEXT_STEPS = (
    "Étapes de la préparation — « launcher mt5 build » (compiler sur une copie), « deploy » (l'EA), « prepare » (preset et configuration de démarrage), "
    "« start » (lancement ou redémarrage contrôlé de MetaTrader 5), « verify » (lecture de l'attachement par le cœur) : chacune a sa commande, ce plan n'en "
    "lance aucune et ne touche à rien dans MetaTrader 5."
)


def _ea_summary(folder: DataFolder) -> str:
    if not folder.eas:
        return (
            "notre agent n'est pas installé dans MQL5\\Experts"
            if folder.experts_present
            else "dossier MQL5\\Experts absent"
        )
    parts = []
    for ea in folder.eas:
        if ea.kind is EaInstallKind.JUNCTION:
            parts.append(f"jonction {ea.name} → {ea.target or '(cible illisible)'}")
        else:
            parts.append(f"dossier {ea.name}")
    return ", ".join(parts)


def _pending(missing: tuple[str, ...], terminal_id: str) -> str:
    options = " ".join(FLAGS[name] for name in missing)
    return f"launcher mt5 register --terminal {terminal_id} {options}"


def _next_for(entry: TerminalEntry) -> str:
    """The next command of a terminal whose declaration is complete: what has been done is read from the registry, what is next is a command to run."""
    if entry.deployment is None:
        return f"launcher mt5 build --terminal {entry.terminal_id}, puis launcher mt5 deploy --terminal {entry.terminal_id}"
    if entry.prepared is None:
        return f"launcher mt5 prepare --terminal {entry.terminal_id}"
    return f"launcher mt5 start --terminal {entry.terminal_id} (--dry-run d'abord), puis launcher mt5 verify --terminal {entry.terminal_id}"


def _planned(installation: Installation, folder: DataFolder, entry: TerminalEntry | None) -> TerminalPlan:
    missing: tuple[str, ...]
    if entry is None:
        status, missing = PlanStatus.UNREGISTERED, ()
        next_step = f"launcher mt5 register --terminal {folder.terminal_id}"
    else:
        missing = entry.declared.missing_fields()
        status = PlanStatus.INCOMPLETE if missing else PlanStatus.DECLARED
        next_step = _pending(missing, folder.terminal_id) if missing else _next_for(entry)
    instance = installation.running[0] if installation.running else None
    return TerminalPlan(
        terminal_id=folder.terminal_id,
        label=entry.label if entry else None,
        install_path=installation.install_path,
        data_path=folder.path,
        portable=folder.portable,
        version=installation.version,
        registered=entry is not None,
        running_pid=instance.pid if instance else None,
        ea_summary=_ea_summary(folder),
        presets_present=folder.presets_present,
        status=status,
        missing=missing,
        next_step=next_step,
    )


def build_mt5_plan(discovery: DiscoveryResult, snapshot: TerminalsSnapshot) -> Mt5Plan:
    registered = {entry.terminal_id: entry for entry in snapshot.terminals}
    terminals: list[TerminalPlan] = []
    seen: set[str] = set()
    for installation in discovery.installations:
        for folder in installation.data_folders:
            seen.add(folder.terminal_id)
            terminals.append(_planned(installation, folder, registered.get(folder.terminal_id)))
    for entry in snapshot.terminals:
        if entry.terminal_id not in seen:
            terminals.append(
                TerminalPlan(
                    terminal_id=entry.terminal_id,
                    label=entry.label,
                    install_path=entry.install_path,
                    data_path=entry.data_path,
                    portable=entry.portable,
                    registered=True,
                    status=PlanStatus.NOT_FOUND,
                    missing=entry.declared.missing_fields(),
                    next_step=f"vérifier le chemin {entry.data_path} ; le registre n'est pas modifié",
                )
            )
    return Mt5Plan(
        observed_at=discovery.observed_at,
        terminals=tuple(terminals),
        registry_problem=snapshot.problem,
        installations_found=len(discovery.installations),
    )


STATUS_LABELS = {
    PlanStatus.UNREGISTERED: "non enregistré",
    PlanStatus.INCOMPLETE: "enregistré, déclaration incomplète",
    PlanStatus.DECLARED: "enregistré, déclaration complète",
    PlanStatus.NOT_FOUND: "enregistré, introuvable sur ce poste",
}


def render_mt5_plan(plan: Mt5Plan) -> str:
    lines = ["Préparation de MetaTrader 5 — lecture seule : rien n'est écrit, rien n'est lancé.", ""]
    if plan.registry_problem:
        lines += [f"! {plan.registry_problem} (aucun terminal n'est tenu pour enregistré)", ""]
    if not plan.installations_found:
        lines += [
            "Aucune installation de MetaTrader 5 détectée.",
            "Enregistrement à la main : launcher mt5 register --install-path <dossier de terminal64.exe> --data-path <dossier de données>"
            " (ou --portable)",
            "",
        ]
    if len(plan.terminals) > 1:
        lines += [
            "Plusieurs terminaux : aucune sélection automatique — le choix se fait avec --terminal <identifiant>.",
            "",
        ]
    for terminal in plan.terminals:
        title = f"Terminal {terminal.terminal_id}" + (f" ({terminal.label})" if terminal.label else "")
        lines.append(title)
        if terminal.status is not PlanStatus.NOT_FOUND:
            running = f", en cours (pid {terminal.running_pid})" if terminal.running_pid is not None else ", arrêté"
            version = f" (version {terminal.version})" if terminal.version else ""
            lines.append(f"  installation : {terminal.install_path}{version}{running}")
        lines.append(f"  données      : {terminal.data_path}{' (portable)' if terminal.portable else ''}")
        if terminal.status is not PlanStatus.NOT_FOUND:
            lines.append(f"  EA           : {terminal.ea_summary}")
            presets = "présent" if terminal.presets_present else "absent (créé au moment du preset, incrément I5)"
            lines.append(f"  Presets      : dossier {presets}")
        lines.append(f"  statut       : {STATUS_LABELS[terminal.status]}")
        if terminal.missing and terminal.status is not PlanStatus.NOT_FOUND:
            lines.append("  manque : " + ", ".join(FIELD_LABELS[name] for name in terminal.missing))
        lines.append(f"  prochaine étape : {terminal.next_step}")
        lines.append("")
    lines.append(NEXT_STEPS)
    return "\n".join(lines)


def mt5_plan_document(plan: Mt5Plan) -> dict[str, Any]:
    document = plan.model_dump(mode="json", by_alias=True)
    document["observedAt"] = iso(plan.observed_at)
    return document
