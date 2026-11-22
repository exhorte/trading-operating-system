"""The plain-text reports of ``launcher mt5 detect`` and ``launcher mt5 list`` (French, like the rest of the launcher). Pure formatting: no I/O."""

from __future__ import annotations

from typing import Any

from trading_os.launcher.mt5.model import (
    FIELD_LABELS,
    DataFolder,
    DeclaredTerminal,
    DiscoveryResult,
    DiscoverySource,
    EaInstallKind,
    Installation,
    TerminalEntry,
    TerminalsSnapshot,
)
from trading_os.shared.time import iso

SOURCE_LABELS = {
    DiscoverySource.REGISTRY: "liste des programmes installés",
    DiscoverySource.KNOWN_DIRECTORY: "dossier connu",
    DiscoverySource.RUNNING_PROCESS: "processus en cours",
    DiscoverySource.REGISTERED: "chemin enregistré",
}


def _running(installation: Installation) -> str:
    if not installation.running:
        return "arrêté"
    parts = []
    for instance in installation.running:
        flags = [
            text
            for flag, text in ((instance.portable, "portable"), (instance.config_file_given, "avec /config"))
            if flag
        ]
        parts.append(f"en cours (pid {instance.pid}{', ' + ', '.join(flags) if flags else ''})")
    return " ; ".join(parts)


def _folder_lines(folder: DataFolder) -> list[str]:
    ea = ", ".join(
        f"jonction {item.name} → {item.target or '(cible illisible)'}"
        if item.kind is EaInstallKind.JUNCTION
        else f"dossier {item.name}"
        for item in folder.eas
    )
    lines = [
        f"  Terminal {folder.terminal_id}{' (portable)' if folder.portable else ''}",
        f"    données : {folder.path}",
        f"    origin  : {folder.origin or '(aucune — dossier portable)'}",
        f"    notre EA : {ea or 'non installé'}",
    ]
    if folder.third_party_experts:
        lines.append("    EA tiers installés (compilés) : " + ", ".join(folder.third_party_experts))
    lines.append(
        "    MQL5\\Presets : "
        + ("présent" if folder.presets_present else "absent")
        + " ; fichier de liaison de l'agent : "
        + ("présent" if folder.link_file_present else "absent")
        + " (son contenu n'est jamais lu)"
    )
    return lines


def render_detect(result: DiscoveryResult) -> str:
    lines = [
        f"Détection de MetaTrader 5 — {iso(result.observed_at)} (lecture seule : rien n'est écrit, rien n'est lancé)",
        "",
    ]
    if not result.installations:
        lines += ["Aucune installation de MetaTrader 5 détectée.", ""]
    for installation in result.installations:
        version = f" (version {installation.version})" if installation.version else ""
        lines.append(f"Installation {installation.install_path}{version}")
        lines.append("  trouvée par : " + ", ".join(SOURCE_LABELS[source] for source in installation.sources))
        lines.append(f"  état : {_running(installation)}")
        for folder in installation.data_folders:
            lines += _folder_lines(folder)
        if not installation.data_folders:
            lines.append("  aucun dossier de données rattaché (le terminal n'a peut-être jamais été lancé)")
        lines.append("")
    for rejected in result.rejected:
        lines.append(f"Candidat refusé : {rejected.path} — {rejected.reason} ({SOURCE_LABELS[rejected.source]})")
    for path in result.unmatched_data_folders:
        lines.append(f"Dossier de données sans installation trouvée : {path}")
    if len(result.installations) > 1:
        lines += ["", "Plusieurs installations : aucune n'est choisie à la place de l'utilisateur."]
    return "\n".join(lines).rstrip()


def _declared_text(declared: DeclaredTerminal) -> str:
    parts = []
    if declared.account_id is not None:
        parts.append(f"compte {declared.account_id}")
    if declared.expected_login is not None:
        parts.append(f"login attendu {declared.expected_login}")
    if declared.chart is not None:
        parts.append(f"graphique {declared.chart.symbol} {declared.chart.period}")
    if declared.magic is not None:
        parts.append(f"numéro magique {declared.magic}")
    if declared.allowed_symbols:
        parts.append("symboles " + ",".join(declared.allowed_symbols))
    if declared.provider is not None:
        parts.append(f"fournisseur {declared.provider}")
    if declared.product is not None:
        parts.append(f"produit {declared.product}")
    return ", ".join(parts) or "rien encore"


def missing_text(declared: DeclaredTerminal) -> str | None:
    missing = declared.missing_fields()
    return "manque : " + ", ".join(FIELD_LABELS[name] for name in missing) if missing else None


def describe_entry(entry: TerminalEntry) -> list[str]:
    lines = [
        f"  {entry.label}  {entry.terminal_id}  [{entry.source.value}]",
        f"    installation : {entry.install_path}",
        f"    données      : {entry.data_path}{' (portable)' if entry.portable else ''}",
        f"    déclaré      : {_declared_text(entry.declared)}",
    ]
    missing = missing_text(entry.declared)
    if missing:
        lines.append(f"    {missing}")
    lines.append(f"    opération    : {entry.operation.kind.value}")
    return lines


def render_list(snapshot: TerminalsSnapshot) -> str:
    lines = ["Terminaux enregistrés (var/launcher/terminals.json) — lecture seule", ""]
    if snapshot.problem:
        lines += [f"! {snapshot.problem} (il n'est pas utilisé)", ""]
    if not snapshot.terminals:
        lines.append("Aucun terminal enregistré.")
    for entry in snapshot.terminals:
        lines += describe_entry(entry)
        lines.append("")
    return "\n".join(lines).rstrip()


def detect_document(result: DiscoveryResult) -> dict[str, Any]:
    return result.model_dump(mode="json", by_alias=True)
