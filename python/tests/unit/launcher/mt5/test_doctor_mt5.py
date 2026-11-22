"""The MetaTrader family of ``launcher doctor`` once the terminals can be found and registered (ADR 0039 § 6, I3). It reports what is *found* — never
that an EA is attached, connected or ready: that is not inspected yet, and the report says so."""

from __future__ import annotations

from datetime import timedelta

from tests.unit.launcher.mt5.support import (
    DATA,
    DATA_ID,
    INSTALL,
    FakeMt5Files,
    FakePrograms,
    add_data_folder,
    add_install,
    clock,
    config,
    declared,
    folder,
    standard_machine,
)
from tests.unit.launcher.support import T0, FakeProcessTable, core_health, make_config, obs
from trading_os.launcher.doctor import DoctorReport, Family, Severity, diagnose, render_doctor
from trading_os.launcher.lock import LockInspection, LockState
from trading_os.launcher.mt5.discovery import Mt5Discovery
from trading_os.launcher.mt5.model import (
    DeclaredTerminal,
    Mt5Facts,
    OperationKind,
    OperationState,
    TerminalEntry,
    TerminalSource,
    TerminalsSnapshot,
)
from trading_os.launcher.mt5.ports import ProgramEntry

FREE = LockInspection(state=LockState.FREE)


def facts(files=None, programs=None, table=None, entries=(), problem=None, error=None):  # type: ignore[no-untyped-def]
    default_files, default_programs, default_table = standard_machine()
    discovery = None
    if error is None:
        discovery = Mt5Discovery(
            config(),
            files=files or default_files,
            programs=programs or default_programs,
            processes=table or default_table,
            clock=clock(),
        ).discover()
    return Mt5Facts(
        discovery=discovery, snapshot=TerminalsSnapshot(terminals=tuple(entries), problem=problem), error=error
    )


def entry(what: DeclaredTerminal | None = None, operation: OperationState | None = None) -> TerminalEntry:
    return TerminalEntry(
        terminal_id=DATA_ID,
        label="exness-demo-01",
        install_path=INSTALL,
        data_path=DATA,
        portable=False,
        source=TerminalSource.DISCOVERED,
        declared=what or DeclaredTerminal(),
        operation=operation or OperationState(),
        registered_at=T0,
        updated_at=T0,
    )


def run(mt5: Mt5Facts | None) -> DoctorReport:
    return diagnose(obs(core_health=core_health()), make_config(), FREE, mt5=mt5)


def codes(report: DoctorReport, severity: Severity | None = None) -> list[str]:
    return [
        c.code for c in report.checks if c.family is Family.METATRADER and (severity is None or c.severity is severity)
    ]


def one(report: DoctorReport, code: str):  # type: ignore[no-untyped-def]
    (found,) = [c for c in report.checks if c.code == code]
    return found


def test_without_any_mt5_facts_the_report_still_says_it_does_not_look() -> None:
    assert codes(run(None)) == ["MT5_NOT_INSPECTED"]


class TestWhatIsFound:
    def test_the_audited_workstation_gives_facts_and_no_problem(self) -> None:
        report = run(facts())
        mt5 = set(codes(report))
        assert {
            "MT5_INSTALLATION_FOUND",
            "MT5_EA_AGENT_JUNCTION",
            "MT5_PRESETS_FOLDER_MISSING",
            "MT5_THIRD_PARTY_EXPERTS",
            "MT5_TERMINAL_UNREGISTERED",
            "MT5_EA_STATE_NOT_INSPECTED",
        } <= mt5
        assert "MT5_NOT_INSPECTED" not in mt5
        assert report.ok is True
        assert not codes(report, Severity.PROBLEM)

    def test_the_installation_is_described_with_its_version_and_its_running_instance(self) -> None:
        check = one(run(facts()), "MT5_INSTALLATION_FOUND")
        assert INSTALL in check.detail and "5.0.0.6230" in check.detail
        assert "pid 1872" in check.detail

    def test_the_agent_junction_is_respected_and_its_target_is_shown(self) -> None:
        check = one(run(facts()), "MT5_EA_AGENT_JUNCTION")
        assert check.severity is Severity.INFO
        assert "mt5-execution-agent" in check.detail

    def test_the_third_party_ea_is_named_as_installed_not_as_attached(self) -> None:
        check = one(run(facts()), "MT5_THIRD_PARTY_EXPERTS")
        assert "Ultimate_ICT_Gold_Scalper_v4.0.ex5" in check.detail
        assert "pas forcément attachés" in check.detail

    def test_an_unregistered_terminal_is_given_the_command_that_registers_it(self) -> None:
        check = one(run(facts()), "MT5_TERMINAL_UNREGISTERED")
        assert f"launcher mt5 register --terminal {DATA_ID}" in (check.remedy or "")

    def test_with_no_registered_terminal_the_state_of_the_ea_is_declared_not_inspected(self) -> None:
        check = one(run(facts()), "MT5_EA_STATE_NOT_INSPECTED")
        assert check.severity is Severity.UNKNOWN
        assert "aucun terminal n'est enregistré" in check.detail

    def test_a_data_folder_without_our_ea_is_information(self) -> None:
        files, programs, table = standard_machine()
        files.directories[DATA.lower() + r"\mql5\experts"] = [folder("Advisors")]
        check = one(run(facts(files, programs, table)), "MT5_EA_NOT_INSTALLED")
        assert check.severity is Severity.INFO


class TestWhenSomethingIsWrongOrMissing:
    def test_no_installation_at_all_is_a_warning_with_the_manual_way_out(self) -> None:
        report = run(facts(FakeMt5Files(), FakePrograms(), FakeProcessTable()))
        check = one(report, "MT5_NONE_FOUND")
        assert check.severity is Severity.WARNING
        assert "launcher mt5 register --install-path" in (check.remedy or "")
        assert report.ok is True

    def test_a_candidate_without_the_executable_is_a_warning_naming_it(self) -> None:
        files = FakeMt5Files()
        files.add_dir(r"D:\Old\MetaTrader 5")
        programs = FakePrograms()
        programs = FakePrograms([ProgramEntry("MetaTrader 5", (r"D:\Old\MetaTrader 5",))])
        check = one(run(facts(files, programs, FakeProcessTable())), "MT5_CANDIDATE_REJECTED")
        assert check.severity is Severity.WARNING
        assert r"D:\Old\MetaTrader 5" in check.detail
        assert check.remedy

    def test_a_discovery_that_failed_is_unknown_not_a_problem_and_not_silence(self) -> None:
        report = run(facts(error="la table des processus ne répond pas"))
        check = one(report, "MT5_DISCOVERY_FAILED")
        assert check.severity is Severity.UNKNOWN
        assert "ne répond pas" in check.detail
        assert report.ok is True

    def test_a_registry_that_cannot_be_read_is_a_warning(self) -> None:
        check = one(run(facts(problem="registre illisible")), "MT5_REGISTRY_UNREADABLE")
        assert check.severity is Severity.WARNING
        assert check.remedy

    def test_a_registered_terminal_that_is_gone_is_a_warning_not_a_deletion(self) -> None:
        report = run(facts(FakeMt5Files(), FakePrograms(), FakeProcessTable(), entries=[entry(declared())]))
        check = one(report, "MT5_TERMINAL_NOT_FOUND")
        assert check.severity is Severity.WARNING
        assert "exness-demo-01" in check.detail
        assert check.remedy

    def test_several_terminals_are_never_chosen_for_the_user(self) -> None:
        files, programs, table = standard_machine()
        add_install(files, r"D:\Brokers\FTMO MT5")
        add_data_folder(files, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", origin=r"D:\Brokers\FTMO MT5")
        files.add_dir(r"D:\Brokers")
        programs = FakePrograms([*programs.programs(), ProgramEntry("MetaTrader 5 FTMO", (r"D:\Brokers\FTMO MT5",))])
        check = one(run(facts(files, programs, table)), "MT5_SEVERAL_TERMINALS")
        assert check.severity is Severity.INFO
        assert "aucune sélection automatique" in check.detail


class TestARegisteredTerminal:
    def test_a_complete_declaration_is_green(self) -> None:
        report = run(facts(entries=[entry(declared())]))
        assert one(report, "MT5_TERMINAL_REGISTERED").severity is Severity.OK
        assert "MT5_TERMINAL_UNREGISTERED" not in codes(report)
        assert "MT5_DECLARATION_INCOMPLETE" not in codes(report)

    def test_an_incomplete_declaration_lists_what_remains_and_is_only_information(self) -> None:
        report = run(facts(entries=[entry(DeclaredTerminal(magic=1))]))
        check = one(report, "MT5_DECLARATION_INCOMPLETE")
        assert check.severity is Severity.INFO
        assert "login attendu" in check.detail
        assert "numéro magique" not in check.detail

    def test_an_operation_in_progress_is_information_with_its_step(self) -> None:
        operation = OperationState(
            kind=OperationKind.DEPLOYING,
            deployment_id="d-1",
            step="copie",
            started_at=T0 - timedelta(seconds=10),
            deadline=T0 + timedelta(seconds=110),
        )
        check = one(run(facts(entries=[entry(declared(), operation)])), "MT5_OPERATION_IN_PROGRESS")
        assert check.severity is Severity.INFO
        assert "copie" in check.detail and "d-1" in check.detail

    def test_an_operation_past_its_deadline_is_a_problem_and_is_never_resumed_silently(self) -> None:
        operation = OperationState(
            kind=OperationKind.EA_LOADING,
            deployment_id="d-2",
            step="hello",
            started_at=T0 - timedelta(seconds=200),
            deadline=T0 - timedelta(seconds=110),
        )
        report = run(facts(entries=[entry(declared(), operation)]))
        check = one(report, "MT5_OPERATION_OVERDUE")
        assert check.severity is Severity.PROBLEM
        assert "LAUNCHER_OPERATION_INTERRUPTED" in check.detail
        assert check.remedy
        assert report.ok is False


class TestEveryFindingTellsWhatToDo:
    def test_a_warning_or_a_problem_always_has_a_remedy(self) -> None:
        past = OperationState(
            kind=OperationKind.DEPLOYING,
            deployment_id="d",
            step="s",
            started_at=T0 - timedelta(hours=1),
            deadline=T0 - timedelta(minutes=1),
        )
        scenarios = [
            facts(FakeMt5Files(), FakePrograms(), FakeProcessTable()),
            facts(problem="illisible"),
            facts(FakeMt5Files(), FakePrograms(), FakeProcessTable(), entries=[entry(declared())]),
            facts(entries=[entry(declared(), past)]),
            facts(error="x"),
        ]
        for mt5 in scenarios:
            offenders = [
                c.code for c in run(mt5).checks if c.severity in {Severity.WARNING, Severity.PROBLEM} and not c.remedy
            ]
            assert not offenders, offenders


def test_the_text_never_calls_a_terminal_or_an_ea_ready() -> None:
    text = render_doctor(run(facts(entries=[entry(declared())]))).lower()
    assert "ea_ready" not in text
    assert "prêt à exécuter" not in text
