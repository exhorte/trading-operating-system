"""The controlled start — or restart — of a MetaTrader 5 terminal with our agent (ADR 0038 § 8, ADR 0039 §§ 3 and 5, I6).

What it will do, in this order, and what stops it:

* **Gates, all evaluated and all shown.** The terminal is the registered one (``origin.txt`` still names its installation); the agent is deployed and is the file
  that was deployed; the preset and the start-up file are prepared and are the files that were prepared. For a terminal that is **open**: it holds no open
  position and no pending order (read from the terminal itself, and a terminal that cannot be read is a refusal, not a pass); it is on the login that was
  declared; and **no worker of the core is attached to it** (R16: a worker that finds MetaTrader closed would start it again, without the agent — the person
  detaches the account first; the launcher never detaches nor attaches one).
* **A typed confirmation** to close an open terminal: the exact phrase ``FERMER <terminal>``. There is no option that skips it.
* **A polite close request, never a kill.** The terminal's windows are asked to close, as the close button does; if it has not gone after the deadline the
  operation ends in ``EA_ERROR`` and the terminal is left as it is. Nothing here ends a process.
* **The start**: ``terminal64.exe /config:<start-up file>``, with no account and no password on the command line, and a wait — bounded — for the agent's ``hello``
  as the core reports it. Silence ends in ``EA_ERROR(MT5_EA_NOT_REPORTING)`` with what can be told (expert advisors disabled in the terminal) and what only
  the person can check (the WebRequest list).

It never closes a position, never changes a mode, never connects or detaches an account, never writes in the terminal. Its states are journalled; it stops at
the agent's connection — whether the terminal is ready is the core's reading, made later and made again.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trading_os.launcher.events import EventLog, EventSeverity, EventType, new_correlation_id
from trading_os.launcher.lock import LauncherBusy
from trading_os.launcher.model import CoreHealth, LauncherConfig
from trading_os.launcher.mt5.deploy import terminal_identity_problems
from trading_os.launcher.mt5.discovery import key_of
from trading_os.launcher.mt5.journal import StateJournal
from trading_os.launcher.mt5.manifest import sha256_file
from trading_os.launcher.mt5.model import OperationKind, TerminalEntry, TerminalSnapshot, TerminalVerdict
from trading_os.launcher.mt5.ports import CenterView, Mt5FilesPort, PositionsProbe
from trading_os.launcher.mt5.states import DeploymentState, StateDecision, is_allowed
from trading_os.launcher.mt5.terminals import RegistryRefused, TerminalRegistry, terminal_lock
from trading_os.launcher.ports import (
    HealthProbe,
    ProbeError,
    ProcessController,
    ProcessSpawner,
    ProcessTable,
    Sleeper,
    SpawnError,
)
from trading_os.shared.time import Clock

S = DeploymentState
TERMINAL_EXE = "terminal64.exe"
CLOSE_TIMEOUT_S = 60.0
APPEAR_TIMEOUT_S = 30.0
EA_LOADING_TIMEOUT_S = 90.0  # ADR 0038
POLL_S = 3.0


class StartRefused(Exception):
    """A start that is not made, with every reason (French: shown to a person)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class Gate:
    code: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class StartPlan:
    terminal_id: str
    exe_path: str
    startup_path: str
    portable: bool
    running_pid: int | None
    gates: tuple[Gate, ...]
    snapshot: TerminalSnapshot | None
    confirmation_phrase: str | None  # what must be typed to close an open terminal

    @property
    def problems(self) -> list[str]:
        return [f"{gate.code} : {gate.detail}" for gate in self.gates if not gate.ok]

    @property
    def needs_close(self) -> bool:
        return self.running_pid is not None


@dataclass(frozen=True)
class StartResult:
    state: DeploymentState
    codes: tuple[str, ...]
    pid: int | None
    closed_previous: bool
    hello_verified: bool | None  # None = the core could not be asked
    verdict: TerminalVerdict | None
    notes: tuple[str, ...]


def running_pid(processes: ProcessTable, exe: str) -> int | None:
    """The pid of the terminal whose executable is exactly this one — another program named terminal64.exe elsewhere is not this terminal."""
    wanted = key_of(exe)
    for process in processes.processes():
        if process.name.lower() == TERMINAL_EXE and process.executable and key_of(process.executable) == wanted:
            return process.pid
    return None


class Mt5Controller:
    def __init__(
        self,
        *,
        files: Mt5FilesPort,
        processes: ProcessTable,
        spawner: ProcessSpawner,
        controller: ProcessController,
        probe: PositionsProbe,
        center: CenterView,
        health: HealthProbe,
        registry: TerminalRegistry,
        events: EventLog,
        clock: Clock,
        sleeper: Sleeper,
        config: LauncherConfig,
        pid: int,
    ) -> None:
        self._files = files
        self._processes = processes
        self._spawner = spawner
        self._controller = controller
        self._probe = probe
        self._center = center
        self._health = health
        self._registry = registry
        self._events = events
        self._clock = clock
        self._sleeper = sleeper
        self._config = config
        self._pid = pid
        self._journal = StateJournal(registry, events, clock)

    # ------------------------------------------------------------------------------------------------ plan (reads; the terminal is only read if it is open)

    def plan(self, entry: TerminalEntry) -> StartPlan:
        exe = entry.install_path.rstrip("\\") + "\\" + TERMINAL_EXE
        gates: list[Gate] = []
        identity = terminal_identity_problems(self._files, entry)
        gates.append(
            Gate(
                "TERMINAL_IDENTITY",
                not identity,
                "; ".join(identity) or "le dossier de données appartient bien à l'installation enregistrée",
            )
        )
        gates.append(
            Gate(
                "TERMINAL_EXE",
                self._files.is_file(exe),
                f"{TERMINAL_EXE} {'présent' if self._files.is_file(exe) else 'introuvable'} dans {entry.install_path}",
            )
        )
        gates.append(self._agent_gate(entry))
        gates.append(self._prepared_gate(entry))
        pid = self._running_pid(exe)
        snapshot: TerminalSnapshot | None = None
        if pid is not None:
            gates.extend(self._open_terminal_gates(entry, exe))
            snapshot = self._last_snapshot
        startup = (
            entry.prepared.startup_path
            if entry.prepared
            else str(self._config.var_dir / "mt5" / entry.terminal_id / "startup.ini")
        )
        return StartPlan(
            terminal_id=entry.terminal_id,
            exe_path=exe,
            startup_path=startup,
            portable=entry.portable,
            running_pid=pid,
            gates=tuple(gates),
            snapshot=snapshot,
            confirmation_phrase=f"FERMER {entry.terminal_id}" if pid is not None else None,
        )

    # ------------------------------------------------------------------------------------------------ start

    def start(self, plan: StartPlan, *, confirmation: str | None = None) -> StartResult:
        entry = self._entry(plan.terminal_id)
        correlation = new_correlation_id()
        if plan.problems:
            self._refuse(entry, correlation, plan.problems)
            raise StartRefused(plan.problems)
        if plan.needs_close and confirmation != plan.confirmation_phrase:
            problems = [
                f"CONFIRMATION : pour fermer un terminal ouvert, tapez exactement « {plan.confirmation_phrase} »"
            ]
            self._refuse(entry, correlation, problems)
            raise StartRefused(problems)
        try:
            with terminal_lock(self._config, plan.terminal_id, self._processes, self._clock, pid=self._pid):
                return self._run(entry, plan, correlation)
        except (RegistryRefused, LauncherBusy) as refused:
            problems = refused.problems if isinstance(refused, RegistryRefused) else [str(refused)]
            self._refuse(entry, correlation, problems)
            raise StartRefused(problems) from refused

    # ------------------------------------------------------------------------------------------------ the run

    def _run(self, entry: TerminalEntry, plan: StartPlan, correlation: str) -> StartResult:
        closed = False
        if plan.running_pid is not None:
            closed_ok, result = self._close(entry, plan, correlation)
            if not closed_ok and result is not None:
                return result
            closed = True
        return self._open(entry, plan, correlation, closed_previous=closed)

    def _close(self, entry: TerminalEntry, plan: StartPlan, correlation: str) -> tuple[bool, StartResult | None]:
        assert plan.running_pid is not None
        self._registry.begin_operation(
            entry.terminal_id,
            OperationKind.TERMINAL_STOPPING,
            deployment_id=correlation,
            step="fermeture contrôlée",
            timeout_s=CLOSE_TIMEOUT_S + 30,
        )
        try:
            self._note_state(entry.terminal_id, S.TERMINAL_STOPPING, (), correlation, "operation")
            self._events.emit(
                EventType.MT5_RESTART_REQUESTED,
                component="mt5",
                correlation_id=correlation,
                instance_id=entry.terminal_id,
                diagnostic="fermeture contrôlée demandée (fenêtre), après confirmation tapée ; positions et ordres : 0",
            )
            if not self._controller.request_window_close(plan.running_pid):
                return False, self._error(
                    entry,
                    correlation,
                    ("TERMINAL_CLOSE_NOT_ASKED",),
                    "la demande de fermeture n'a atteint aucune fenêtre du terminal",
                )
            waited = 0.0
            while self._running_pid(plan.exe_path) == plan.running_pid:
                if waited >= CLOSE_TIMEOUT_S:
                    return False, self._error(
                        entry,
                        correlation,
                        ("TERMINAL_CLOSE_TIMEOUT",),
                        f"le terminal ne s'est pas fermé en {CLOSE_TIMEOUT_S:g} s : il est laissé tel quel (le lanceur ne tue jamais MetaTrader)",
                    )
                self._sleeper.sleep(1.0)
                waited += 1.0
            self._note_state(entry.terminal_id, S.DEPLOYED, (), correlation, "observation")
        finally:
            self._registry.end_operation(entry.terminal_id)
        return True, None

    def _open(self, entry: TerminalEntry, plan: StartPlan, correlation: str, *, closed_previous: bool) -> StartResult:
        terminal = entry.terminal_id
        self._registry.begin_operation(
            terminal,
            OperationKind.TERMINAL_STARTING,
            deployment_id=correlation,
            step="lancement",
            timeout_s=APPEAR_TIMEOUT_S + 30,
        )
        try:
            self._note_state(terminal, S.TERMINAL_STARTING, (), correlation, "operation")
            arguments = [plan.exe_path, f"/config:{plan.startup_path}"] + (["/portable"] if plan.portable else [])
            try:
                pid = self._spawner.spawn(
                    arguments, cwd=Path(entry.install_path), log_path=self._config.logs_dir / f"mt5-{terminal}.log"
                )
            except SpawnError as error:
                return self._error(
                    entry,
                    correlation,
                    ("TERMINAL_NOT_STARTED",),
                    f"MetaTrader 5 n'a pas pu être lancé : {error}",
                    closed_previous=closed_previous,
                )
            waited = 0.0
            while self._running_pid(plan.exe_path) is None:
                if waited >= APPEAR_TIMEOUT_S:
                    return self._error(
                        entry,
                        correlation,
                        ("TERMINAL_NOT_STARTED",),
                        f"le terminal n'est pas apparu en {APPEAR_TIMEOUT_S:g} s",
                        closed_previous=closed_previous,
                    )
                self._sleeper.sleep(1.0)
                waited += 1.0
            self._events.emit(
                EventType.MT5_TERMINAL_STARTED,
                component="mt5",
                correlation_id=correlation,
                instance_id=terminal,
                diagnostic=f"terminal lancé (pid {pid}) avec le fichier de démarrage du lanceur",
            )
        finally:
            self._registry.end_operation(terminal)
        return self._wait_for_agent(entry, plan, correlation, pid, closed_previous=closed_previous)

    def _wait_for_agent(
        self, entry: TerminalEntry, plan: StartPlan, correlation: str, pid: int, *, closed_previous: bool
    ) -> StartResult:
        terminal = entry.terminal_id
        self._registry.begin_operation(
            terminal,
            OperationKind.EA_LOADING,
            deployment_id=correlation,
            step="attente du hello de l'agent",
            timeout_s=EA_LOADING_TIMEOUT_S + 30,
        )
        try:
            self._note_state(terminal, S.EA_LOADING, (), correlation, "operation")
            waited = 0.0
            while True:
                facts = self._center.terminal_facts(entry)
                if not facts.reachable:
                    notes = ("le cœur ne répond pas : l'attachement de l'agent n'a pas pu être vérifié",)
                    return StartResult(S.EA_LOADING, ("CORE_UNREACHABLE",), pid, closed_previous, None, None, notes)
                if facts.hello_received:
                    self._note_state(terminal, S.EA_CONNECTED, ("HELLO_RECEIVED",), correlation, "observation")
                    self._events.emit(
                        EventType.MT5_EA_CONNECTED,
                        component="mt5",
                        correlation_id=correlation,
                        instance_id=terminal,
                        diagnostic="hello de l'agent reçu par le cœur",
                    )
                    return StartResult(
                        S.EA_CONNECTED, ("HELLO_RECEIVED",), pid, closed_previous, True, facts.verdict, ()
                    )
                if waited >= EA_LOADING_TIMEOUT_S:
                    return self._not_reporting(entry, correlation, pid, closed_previous)
                self._sleeper.sleep(POLL_S)
                waited += POLL_S
        finally:
            self._registry.end_operation(terminal)

    def _not_reporting(self, entry: TerminalEntry, correlation: str, pid: int, closed_previous: bool) -> StartResult:
        codes = ["MT5_EA_NOT_REPORTING"]
        notes = [f"aucun hello de l'agent en {EA_LOADING_TIMEOUT_S:g} s"]
        if self._files.experts_enabled(entry.data_path) is False:
            codes.append("MT5_EXPERTS_DISABLED")
            notes.append(
                "les experts sont désactivés dans MetaTrader (Outils > Options > Experts) : le lanceur n'écrit jamais ce réglage, c'est à vous de l'activer"
            )
        notes.append(
            "à vérifier par vous : Outils > Options > Experts > « Autoriser WebRequest pour les URL listées » doit contenir 127.0.0.1 (non vérifiable de l'extérieur)"
        )
        self._note_state(entry.terminal_id, S.EA_ERROR, tuple(codes), correlation, "operation")
        self._events.emit(
            EventType.MT5_EA_NOT_REPORTING,
            component="mt5",
            correlation_id=correlation,
            severity=EventSeverity.ERROR,
            instance_id=entry.terminal_id,
            diagnostic=" ; ".join(notes),
        )
        return StartResult(S.EA_ERROR, tuple(codes), pid, closed_previous, False, None, tuple(notes))

    # ------------------------------------------------------------------------------------------------ gates

    _last_snapshot: TerminalSnapshot | None = None

    def _agent_gate(self, entry: TerminalEntry) -> Gate:
        record = entry.deployment
        if record is None:
            return Gate(
                "AGENT_DEPLOYED", False, "aucun agent n'est déployé sur ce terminal : « launcher mt5 deploy » d'abord"
            )
        target = Path(record.target_file)
        if not target.is_file() or sha256_file(target) != record.ex5_sha256:
            return Gate(
                "AGENT_DEPLOYED", False, "l'agent déployé a disparu ou a changé depuis son déploiement : redéployez-le"
            )
        return Gate("AGENT_DEPLOYED", True, f"agent {record.agent_version} déployé, empreinte conforme")

    def _prepared_gate(self, entry: TerminalEntry) -> Gate:
        record = entry.prepared
        if record is None:
            return Gate("PRESET_PREPARED", False, "le terminal n'est pas préparé : « launcher mt5 prepare » d'abord")
        for path, digest in (
            (Path(record.preset_path), record.preset_sha256),
            (Path(record.startup_path), record.startup_sha256),
        ):
            if not path.is_file() or sha256_file(path) != digest:
                return Gate(
                    "PRESET_PREPARED",
                    False,
                    f"{path.name} a disparu ou a changé depuis la préparation : refaites « launcher mt5 prepare »",
                )
        return Gate("PRESET_PREPARED", True, "preset et fichier de démarrage conformes à la préparation")

    def _open_terminal_gates(self, entry: TerminalEntry, exe: str) -> list[Gate]:
        gates: list[Gate] = []
        self._last_snapshot = None
        try:
            snapshot = self._probe.read(exe)
        except ProbeError as error:
            return [Gate("TERMINAL_READABLE", False, f"{error} — un terminal qu'on ne peut pas lire n'est pas fermé")]
        self._last_snapshot = snapshot
        gates.append(
            Gate("NO_OPEN_POSITIONS", snapshot.positions == 0, f"{_count(snapshot.positions)} position(s) ouverte(s)")
        )
        gates.append(Gate("NO_PENDING_ORDERS", snapshot.orders == 0, f"{_count(snapshot.orders)} ordre(s) en attente"))
        expected = entry.declared.expected_login
        if expected is None:
            gates.append(Gate("LOGIN_MATCHES", False, "aucun login attendu n'est déclaré pour ce terminal"))
        else:
            gates.append(
                Gate(
                    "LOGIN_MATCHES",
                    snapshot.login == expected,
                    f"le terminal est sur le login {snapshot.login or 'inconnu'}, le login déclaré est {expected}",
                )
            )
        gates.extend(self._core_gates())
        return gates

    def _core_gates(self) -> list[Gate]:
        """What the core could do to the terminal once it is closed — read once, from the core's open health (ADR 0039 R16, ADR 0043).

        A worker that finds MetaTrader closed starts it again, without the agent. Two things put a worker there: one already attached (the count), and the
        pilot, which looks again every few seconds and attaches the account by itself — so a count of zero at one instant is not enough while it is at work.
        A person who detaches the account puts the pilot to rest too (``POST /api/accounts/{id}/disconnect``); the launcher itself never detaches nor attaches one."""
        health = self._health.core_health(f"http://{self._config.api_host}:{self._config.api_port}/api/system/health")
        if health is None:
            return [
                Gate("CORE_WORKER_DETACHED", True, "le cœur ne répond pas : aucun worker ne peut rouvrir MetaTrader"),
                Gate("AUTOPILOT_PAUSED", True, "le cœur ne répond pas : aucun pilote ne peut rattacher le compte"),
            ]
        return [self._worker_gate(health), self._pilot_gate(health)]

    @staticmethod
    def _worker_gate(health: CoreHealth) -> Gate:
        if health.mt5_workers is None:
            return Gate(
                "CORE_WORKER_DETACHED",
                False,
                "le cœur répond mais ne dit pas combien de workers MT5 sont vivants : par prudence, détachez le compte d'abord",
            )
        if health.mt5_workers.alive > 0:
            return Gate(
                "CORE_WORKER_DETACHED",
                False,
                f"{health.mt5_workers.alive} worker(s) MT5 du cœur sont attachés : s'il trouve MetaTrader fermé, il le relance sans l'agent (R16). "
                "Détachez le compte dans le cockpit (Settings) avant — cela met aussi le pilote automatique en pause (ADR 0043) ; "
                "le lanceur ne détache ni ne rattache jamais un compte",
            )
        return Gate("CORE_WORKER_DETACHED", True, "aucun worker du cœur n'est attaché")

    @staticmethod
    def _pilot_gate(health: CoreHealth) -> Gate:
        if health.autopilot_active is None:
            return Gate(
                "AUTOPILOT_PAUSED",
                False,
                "le cœur répond mais ne dit pas si le pilote automatique est actif (cœur plus ancien) : par prudence, redémarrez-le ou arrêtez-le "
                "avant de fermer MetaTrader",
            )
        if health.autopilot_active:
            return Gate(
                "AUTOPILOT_PAUSED",
                False,
                "le pilote automatique est actif : il rattache le compte tout seul (ADR 0043) et, MetaTrader fermé, un worker le relancerait sans "
                "l'agent (R16). Détachez le compte dans le cockpit (Settings) : cela met le pilote en pause jusqu'au prochain « démarrer le système » "
                "ou redémarrage du cœur",
            )
        return Gate(
            "AUTOPILOT_PAUSED", True, "le pilote automatique est éteint ou en pause : il ne rattachera pas le compte"
        )

    # ------------------------------------------------------------------------------------------------ helpers

    def _entry(self, terminal_id: str) -> TerminalEntry:
        snapshot = self._registry.load()
        entry = snapshot.find(terminal_id)
        if entry is None:
            raise StartRefused([f"terminal inconnu : {terminal_id}"])
        return entry

    def _running_pid(self, exe: str) -> int | None:
        return running_pid(self._processes, exe)

    def _note_state(
        self, terminal_id: str, state: DeploymentState, codes: tuple[str, ...], correlation: str, trigger: str
    ) -> None:
        entry = self._entry(terminal_id)
        last = DeploymentState(entry.last_state.state) if entry.last_state else None
        anomaly = last is not None and last is not state and not is_allowed(last, state)
        self._journal.record(
            entry, StateDecision(state=state, codes=codes, anomaly=anomaly), trigger=trigger, correlation_id=correlation
        )

    def _error(
        self,
        entry: TerminalEntry,
        correlation: str,
        codes: tuple[str, ...],
        note: str,
        *,
        closed_previous: bool = False,
    ) -> StartResult:
        self._note_state(entry.terminal_id, S.EA_ERROR, codes, correlation, "operation")
        self._events.emit(
            EventType.MT5_START_FAILED,
            component="mt5",
            correlation_id=correlation,
            severity=EventSeverity.ERROR,
            instance_id=entry.terminal_id,
            diagnostic=f"{', '.join(codes)} : {note}",
        )
        return StartResult(S.EA_ERROR, codes, None, closed_previous, None, None, (note,))

    def _refuse(self, entry: TerminalEntry, correlation: str, problems: list[str]) -> None:
        self._events.emit(
            EventType.MT5_TERMINAL_CLOSE_REFUSED,
            component="mt5",
            correlation_id=correlation,
            severity=EventSeverity.WARNING,
            instance_id=entry.terminal_id,
            diagnostic="; ".join(problems),
        )


def _count(value: int | None) -> str:
    return str(value) if value is not None else "un nombre inconnu de"
