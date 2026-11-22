"""``launcher mt5 plan`` (ADR 0039, I3): what the preparation of MetaTrader 5 would do next, from what is found and what is registered. A pure
function — it chooses nothing for the user and says plainly which steps do not exist yet."""

from __future__ import annotations

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
    standard_machine,
)
from tests.unit.launcher.support import T0, FakeProcessTable
from trading_os.launcher.mt5.discovery import Mt5Discovery
from trading_os.launcher.mt5.model import (
    DeclaredTerminal,
    OperationState,
    PlanStatus,
    TerminalEntry,
    TerminalSource,
    TerminalsSnapshot,
)
from trading_os.launcher.mt5.plan import build_mt5_plan, mt5_plan_document, render_mt5_plan
from trading_os.launcher.mt5.ports import ProgramEntry
from trading_os.shared.time import iso


def found(files=None, programs=None, table=None):  # type: ignore[no-untyped-def]
    default_files, default_programs, default_table = standard_machine()
    return Mt5Discovery(
        config(),
        files=files or default_files,
        programs=programs or default_programs,
        processes=table or default_table,
        clock=clock(),
    ).discover()


def entry(what: DeclaredTerminal | None = None, terminal_id: str = DATA_ID) -> TerminalEntry:
    return TerminalEntry(
        terminal_id=terminal_id,
        label="exness-demo-01",
        install_path=INSTALL,
        data_path=DATA,
        portable=False,
        source=TerminalSource.DISCOVERED,
        declared=what or DeclaredTerminal(),
        operation=OperationState(),
        registered_at=T0,
        updated_at=T0,
    )


def snapshot(*entries: TerminalEntry, problem: str | None = None) -> TerminalsSnapshot:
    return TerminalsSnapshot(terminals=tuple(entries), problem=problem)


EMPTY = snapshot()


def nothing_found():  # type: ignore[no-untyped-def]
    return found(FakeMt5Files(), FakePrograms(), FakeProcessTable())


class TestWhenNothingIsFound:
    def test_it_says_so_and_shows_how_to_register_a_terminal_by_hand(self) -> None:
        text = render_mt5_plan(build_mt5_plan(nothing_found(), EMPTY))
        assert "aucune installation de metatrader 5" in text.lower()
        assert "launcher mt5 register --install-path" in text

    def test_there_is_nothing_to_prepare(self) -> None:
        assert build_mt5_plan(nothing_found(), EMPTY).terminals == ()


class TestADiscoveredTerminal:
    def test_an_unregistered_terminal_is_proposed_for_registration_by_its_identifier(self) -> None:
        plan = build_mt5_plan(found(), EMPTY)
        (terminal,) = plan.terminals
        assert terminal.status is PlanStatus.UNREGISTERED
        assert terminal.registered is False
        assert f"launcher mt5 register --terminal {DATA_ID}" in terminal.next_step
        text = render_mt5_plan(plan)
        assert "non enregistré" in text
        assert DATA_ID in text

    def test_what_is_seen_is_shown_the_running_terminal_the_agent_junction_and_the_missing_presets(self) -> None:
        text = render_mt5_plan(build_mt5_plan(found(), EMPTY))
        assert "en cours (pid 1872)" in text
        assert "jonction" in text
        assert "Presets" in text

    def test_a_partial_declaration_lists_exactly_what_is_missing_and_nothing_else(self) -> None:
        plan = build_mt5_plan(found(), snapshot(entry(DeclaredTerminal(magic=486046))))
        (terminal,) = plan.terminals
        assert terminal.status is PlanStatus.INCOMPLETE
        assert "magic" not in terminal.missing
        assert {"account_id", "expected_login", "chart", "allowed_symbols", "provider", "product"} == set(
            terminal.missing
        )
        (line,) = [line for line in render_mt5_plan(plan).splitlines() if "manque :" in line]
        assert "login attendu" in line
        assert "numéro magique" not in line

    def test_a_complete_declaration_leads_to_the_next_command(self) -> None:
        plan = build_mt5_plan(found(), snapshot(entry(declared())))
        (terminal,) = plan.terminals
        assert terminal.status is PlanStatus.DECLARED
        assert terminal.missing == ()
        text = render_mt5_plan(plan)
        assert "déclaration complète" in text
        assert "launcher mt5 build" in text and "launcher mt5 deploy" in text

    def test_a_registered_terminal_that_is_no_longer_found_is_reported_not_forgotten(self) -> None:
        plan = build_mt5_plan(nothing_found(), snapshot(entry(declared())))
        (terminal,) = plan.terminals
        assert terminal.status is PlanStatus.NOT_FOUND
        assert "introuvable sur ce poste" in render_mt5_plan(plan)

    def test_a_registry_that_cannot_be_read_is_said_and_nothing_is_taken_as_registered(self) -> None:
        plan = build_mt5_plan(found(), snapshot(problem="registre illisible"))
        assert plan.registry_problem == "registre illisible"
        assert "registre illisible" in render_mt5_plan(plan)
        assert plan.terminals[0].status is PlanStatus.UNREGISTERED


class TestSeveralTerminals:
    def machine(self):  # type: ignore[no-untyped-def]
        files, programs, table = standard_machine()
        add_install(files, r"D:\Brokers\FTMO MT5")
        add_data_folder(files, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", origin=r"D:\Brokers\FTMO MT5")
        files.add_dir(r"D:\Brokers")
        programs = FakePrograms([*programs.programs(), ProgramEntry("MetaTrader 5 FTMO", (r"D:\Brokers\FTMO MT5",))])
        return files, programs, table

    def test_every_terminal_is_listed_and_none_is_chosen(self) -> None:
        plan = build_mt5_plan(found(*self.machine()), EMPTY)
        assert [t.terminal_id for t in plan.terminals] == [DATA_ID, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"]
        text = render_mt5_plan(plan)
        assert "plusieurs terminaux" in text.lower()
        assert "aucune sélection automatique" in text

    def test_a_single_terminal_does_not_get_that_warning(self) -> None:
        assert "plusieurs terminaux" not in render_mt5_plan(build_mt5_plan(found(), EMPTY)).lower()


class TestNothingDeeperIsClaimed:
    def test_the_plan_lists_the_steps_and_their_commands_and_says_it_runs_none(self) -> None:
        text = render_mt5_plan(build_mt5_plan(found(), EMPTY))
        for step in ("launcher mt5 build", "« deploy »", "« prepare »", "« start »", "« verify »"):
            assert step in text
        assert "n'en lance aucune" in text

    def test_it_never_says_a_terminal_or_the_ea_is_ready(self) -> None:
        text = render_mt5_plan(build_mt5_plan(found(), snapshot(entry(declared())))).lower()
        assert "ea_ready" not in text
        assert "prêt à exécuter" not in text
        assert "armé" not in text.replace("n'arme", "")


class TestTheDocument:
    def test_it_is_json_serialisable_camel_cased_and_carries_the_time(self) -> None:
        document = mt5_plan_document(build_mt5_plan(found(), EMPTY))
        assert document["observedAt"] == iso(T0)
        terminal = document["terminals"][0]
        assert terminal["terminalId"] == DATA_ID
        assert terminal["status"] == "UNREGISTERED"
