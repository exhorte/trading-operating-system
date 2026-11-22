"""Looking at a terminal (ADR 0039 §§ 3 and 5, I6 and I7): what is observed, the state it makes, and how it reads.

Observation only: the process table says whether the terminal runs, the files say whether the deployed agent is the one that was deployed, the core says whether
the agent said hello and how it reads the conditions. The state is a *synthesis* of those and of the last state journalled; nothing here starts, stops or writes
(journalling a change of state is the caller's act). The synthesis stops at ``EA_READY`` and the authorization to execute is a separate line.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trading_os.launcher.mt5.control import TERMINAL_EXE, running_pid
from trading_os.launcher.mt5.manifest import sha256_file
from trading_os.launcher.mt5.model import CenterFacts, TerminalEntry
from trading_os.launcher.mt5.ports import CenterView
from trading_os.launcher.mt5.states import DeploymentState, StateDecision, StateFacts, synthesize
from trading_os.launcher.ports import ProcessTable
from trading_os.shared.time import Clock


@dataclass(frozen=True)
class TerminalObservation:
    entry: TerminalEntry
    running_pid: int | None
    deployed: bool
    center: CenterFacts
    facts: StateFacts
    decision: StateDecision


def agent_is_deployed(entry: TerminalEntry) -> bool:
    """An agent is recorded and the file at its target is, byte for byte, the one that was deployed."""
    record = entry.deployment
    if record is None:
        return False
    target = Path(record.target_file)
    return target.is_file() and sha256_file(target) == record.ex5_sha256


def observe_terminal(
    entry: TerminalEntry, *, processes: ProcessTable, center: CenterView, clock: Clock
) -> TerminalObservation:
    exe = entry.install_path.rstrip("\\") + "\\" + TERMINAL_EXE
    pid = running_pid(processes, exe)
    deployed = agent_is_deployed(entry)
    asked = center.terminal_facts(entry)
    verdict = asked.verdict
    facts = StateFacts(
        registered=True,
        deployed=deployed,
        operation=entry.operation,
        now=clock.now(),
        terminal_running=pid is not None,
        core_reachable=asked.reachable,
        hello_received=asked.hello_received if asked.reachable else None,
        verdict=verdict.verdict if verdict else None,
        block_codes=verdict.red_codes if verdict else (),
        last_state=DeploymentState(entry.last_state.state) if entry.last_state else None,
    )
    return TerminalObservation(entry, pid, deployed, asked, facts, synthesize(facts))


# ------------------------------------------------------------------------------------------------ rendering


def render_observation(observation: TerminalObservation) -> str:
    entry, decision, asked = observation.entry, observation.decision, observation.center
    verdict = asked.verdict
    lines = [
        f"Terminal {entry.terminal_id} ({entry.label})",
        f"  MT5 Process            : {'en cours (pid ' + str(observation.running_pid) + ')' if observation.running_pid else 'arrêté'}",
        f"  Deployment Status      : {decision.state.value}"
        + (f" — {', '.join(decision.codes)}" if decision.codes else ""),
        f"  Agent déployé          : {_deployment(entry, observation.deployed)}",
    ]
    if not asked.reachable:
        lines.append("  Cœur                   : ne répond pas — l'attachement de l'agent n'est pas observable")
    else:
        lines.append(f"  EA Communication       : {'hello reçu' if asked.hello_received else 'aucun hello'}")
        if verdict is not None and asked.hello_received:
            age = f"{verdict.heartbeat_age_s:.0f} s" if verdict.heartbeat_age_s is not None else "inconnu"
            lines.append(f"  Heartbeat              : dernier il y a {age} ; agent {verdict.agent_version or '?'}")
            lines.append(f"  Lecture du cœur        : {verdict.verdict or 'inconnue'}")
            if verdict.header_code:
                lines.append(f"  En-tête                : {verdict.header_code}")
            if verdict.red_codes:
                lines.append(f"  Reason (rouge)         : {', '.join(verdict.red_codes)}")
            if verdict.pending_codes:
                lines.append(f"  Reason (en attente)    : {', '.join(verdict.pending_codes)}")
            if verdict.warning_codes:
                lines.append(f"  Avertissements         : {', '.join(verdict.warning_codes)}")
            lines.append(f"  Execution Authorization: {verdict.execution_authorization or 'inconnue'}")
    if decision.anomaly:
        lines.append("  ⚠ saut hors de la table des transitions : enregistré comme anomalie")
    return "\n".join(lines)


def _deployment(entry: TerminalEntry, deployed: bool) -> str:
    record = entry.deployment
    if record is None:
        return "aucun"
    return f"{record.agent_version} ({record.ex5_sha256[:12]}…)" + (
        "" if deployed else " — le fichier a disparu ou a changé"
    )


def render_verify(observation: TerminalObservation) -> str:
    verdict = observation.center.verdict
    if not observation.center.reachable:
        return "Le cœur ne répond pas : rien à vérifier (« TradingOS.bat Infrastructure » le démarre)."
    if verdict is None or not observation.center.hello_received:
        return "Le cœur répond mais l'agent de ce terminal n'a pas dit hello : aucune condition n'est évaluable au-delà de l'attente du hello."
    marks = {"GREEN": "OK     ", "RED": "ROUGE  ", "PENDING": "ATTENTE"}
    lines = [f"Conditions de {observation.entry.terminal_id} — lecture du cœur : {verdict.verdict}"]
    lines += [f"  [{marks.get(c.light, c.light)}] {c.label} — {c.detail}" for c in verdict.conditions]
    if verdict.warning_codes:
        lines.append("Avertissements : " + ", ".join(verdict.warning_codes))
    lines.append(
        f"Autorisation d'exécuter : {verdict.execution_authorization or 'inconnue'} (ligne séparée : ce n'est pas la préparation)"
    )
    return "\n".join(lines)
