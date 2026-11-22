"""``launcher doctor`` (ADR 0039, § 6 — I2b, infrastructure side): a **pure** diagnosis of what the launcher can observe. It explains, it never
repairs: no file is written, no process started, no configuration touched. What it cannot see (MetaTrader, the EA) it says it cannot see."""

from __future__ import annotations

import json

import pytest

from tests.unit.launcher.support import T0, core_health, facts, make_config, obs
from trading_os.launcher.doctor import (
    Check,
    DoctorReport,
    Family,
    Severity,
    diagnose,
    doctor_document,
    render_doctor,
)
from trading_os.launcher.lock import LockInspection, LockState
from trading_os.launcher.model import Component, ComponentState, Mt5WorkersFacts, Ownership

FREE = LockInspection(state=LockState.FREE)


def run(observation=None, lock: LockInspection = FREE) -> DoctorReport:  # type: ignore[no-untyped-def]
    return diagnose(observation or obs(core_health=core_health()), make_config(), lock)


def codes(report: DoctorReport, severity: Severity | None = None, family: Family | None = None) -> set[str]:
    return {
        check.code
        for check in report.checks
        if (severity is None or check.severity is severity) and (family is None or check.family is family)
    }


def one(report: DoctorReport, code: str) -> Check:
    found = [check for check in report.checks if check.code == code]
    assert len(found) == 1, (code, [c.code for c in report.checks])
    return found[0]


class TestAHealthyMachine:
    def test_nothing_is_a_problem_and_the_report_is_ok(self) -> None:
        report = run()
        assert report.ok is True
        assert not codes(report, Severity.PROBLEM)
        assert not codes(report, Severity.WARNING)

    def test_each_prerequisite_and_component_is_reported_green(self) -> None:
        report = run()
        assert {"ENV_DOCKER_OK", "ENV_VENV_OK", "ENV_FILE_OK", "ENV_NPM_OK"} <= codes(report, Severity.OK)
        assert {"DATABASE_HEALTHY", "CORE_HEALTHY", "COCKPIT_HEALTHY"} <= codes(report, Severity.OK)

    def test_a_process_the_launcher_did_not_start_is_said_to_be_not_its_own_and_how_to_change_that(self) -> None:
        report = run()
        check = one(report, "CORE_NOT_OWNED")
        assert check.severity is Severity.INFO
        assert "adopt core" in (check.remedy or "")

    def test_the_database_is_a_container_it_is_never_told_to_be_adopted_nor_called_hand_started(self) -> None:
        """``launcher adopt database`` is refused (« la base est un conteneur »): advice to run it would be advice that cannot work."""
        check = one(run(), "DATABASE_NOT_OWNED")
        assert check.severity is Severity.INFO
        assert "launcher adopt" not in (
            check.remedy or ""
        )  # the command, not the word: « un conteneur ne s'adopte pas » is fine
        assert "--include-database" in (check.remedy or "")
        assert "à la main" not in check.detail
        assert "conteneur" in check.detail

    def test_the_adoption_advice_is_given_once_per_component_not_repeated_under_the_launcher(self) -> None:
        advice = [c.code for c in run().checks if c.remedy and "launcher adopt" in c.remedy]
        assert advice == ["CORE_NOT_OWNED", "COCKPIT_NOT_OWNED"]

    def test_a_process_the_launcher_owns_is_said_so(self) -> None:
        report = run(
            obs(
                core_health=core_health(),
                ownerships={Component.CORE: Ownership.OWNED},
            )
        )
        assert one(report, "CORE_OWNED").severity is Severity.OK
        assert "CORE_NOT_OWNED" not in codes(report)

    def test_every_check_carries_its_time_family_subject_and_detail(self) -> None:
        for check in run().checks:
            assert check.observed_at == T0
            assert isinstance(check.family, Family)
            assert check.subject
            assert check.detail
            assert check.code == check.code.upper()


class TestEnvironment:
    def test_docker_that_does_not_answer_is_a_problem_the_launcher_will_not_fix(self) -> None:
        report = run(obs(database=ComponentState.UNAVAILABLE, environment=facts(docker=False)))
        check = one(report, "ENV_DOCKER_UNAVAILABLE")
        assert check.severity is Severity.PROBLEM
        assert "Docker Desktop" in (check.remedy or "")
        assert "ne le démarre pas" in (check.remedy or "") or "ne le lance pas" in (check.remedy or "")
        assert report.ok is False

    def test_the_database_it_cannot_judge_is_unknown_not_a_second_problem(self) -> None:
        report = run(obs(database=ComponentState.UNAVAILABLE, environment=facts(docker=False)))
        assert one(report, "DATABASE_UNAVAILABLE").severity is Severity.UNKNOWN

    @pytest.mark.parametrize(
        ("environment", "code"),
        [
            (facts(venv=False), "ENV_VENV_MISSING"),
            (facts(env_file=False), "ENV_FILE_MISSING"),
            (facts(npm=False), "ENV_NPM_MISSING"),
        ],
    )
    def test_a_missing_prerequisite_is_a_problem_with_a_remedy(self, environment, code: str) -> None:  # type: ignore[no-untyped-def]
        report = run(obs(environment=environment, core_health=core_health()))
        check = one(report, code)
        assert check.severity is Severity.PROBLEM
        assert check.remedy
        assert report.ok is False

    def test_the_env_file_is_only_ever_said_present_never_read(self) -> None:
        assert "jamais lu" in one(run(), "ENV_FILE_OK").detail


class TestComponents:
    @pytest.mark.parametrize("component", [Component.DATABASE, Component.CORE, Component.COCKPIT])
    def test_a_component_that_is_not_running_is_information_not_a_problem(self, component: Component) -> None:
        states = {component.value: ComponentState.ABSENT}
        report = run(obs(**states))  # type: ignore[arg-type]
        check = one(report, f"{component.value.upper()}_ABSENT")
        assert check.severity is Severity.INFO
        assert "start" in (check.remedy or "") or "Infrastructure" in (check.remedy or "")
        assert report.ok is True

    def test_a_component_that_is_still_starting_is_a_warning(self) -> None:
        report = run(obs(cockpit=ComponentState.STARTING, core_health=core_health()))
        assert one(report, "COCKPIT_STARTING").severity is Severity.WARNING

    def test_an_unhealthy_component_is_a_problem_and_is_never_said_to_be_restarted(self) -> None:
        report = run(obs(core=ComponentState.UNHEALTHY, details={Component.CORE: "le cœur n'a pas répondu"}))
        check = one(report, "CORE_UNHEALTHY")
        assert check.severity is Severity.PROBLEM
        assert "le cœur n'a pas répondu" in check.detail
        assert "ne relance jamais" in (check.remedy or "")

    def test_a_foreign_process_on_a_port_is_a_problem_and_the_launcher_will_not_kill_it(self) -> None:
        report = run(obs(cockpit=ComponentState.FOREIGN, core_health=core_health()))
        check = one(report, "COCKPIT_PORT_FOREIGN")
        assert check.severity is Severity.PROBLEM
        assert "jamais" in (check.remedy or "")
        assert "COCKPIT_NOT_OWNED" not in codes(report)

    def test_a_warning_of_the_observation_is_carried_over(self) -> None:
        report = run(
            obs(core_health=core_health(), warnings={Component.COCKPIT: ("écoute sur toutes les interfaces",)})
        )
        warned = [c for c in report.checks if c.code == "COCKPIT_WARNING"]
        assert len(warned) == 1
        assert warned[0].severity is Severity.WARNING
        assert "toutes les interfaces" in warned[0].detail


class TestTheLauncherItself:
    def test_a_registry_that_cannot_be_read_is_a_warning(self) -> None:
        report = run(obs(core_health=core_health(), registry_problem="state.json illisible"))
        check = one(report, "LAUNCHER_REGISTRY_UNREADABLE")
        assert check.severity is Severity.WARNING
        assert "state.json illisible" in check.detail

    def test_a_free_lock_is_green(self) -> None:
        assert one(run(), "LAUNCHER_LOCK_FREE").severity is Severity.OK

    def test_a_lock_held_by_a_live_launcher_is_information(self) -> None:
        report = run(lock=LockInspection(state=LockState.HELD, pid=4242))
        check = one(report, "LAUNCHER_BUSY")
        assert check.severity is Severity.INFO
        assert "4242" in check.detail

    def test_a_stale_lock_is_a_warning_and_the_diagnosis_leaves_it_alone(self) -> None:
        report = run(lock=LockInspection(state=LockState.STALE, pid=999))
        check = one(report, "LAUNCHER_LOCK_STALE")
        assert check.severity is Severity.WARNING
        assert "ne touche à rien" in (check.remedy or "")

    def test_with_nothing_owned_it_says_stop_would_stop_nothing(self) -> None:
        assert "n'arrêterait rien" in one(run(), "LAUNCHER_NOTHING_OWNED").detail


class TestTheCoreView:
    def test_a_core_that_does_not_answer_leaves_the_view_unknown(self) -> None:
        report = run(obs(core=ComponentState.ABSENT, core_health=None))
        assert one(report, "CORE_VIEW_UNAVAILABLE").severity is Severity.UNKNOWN
        assert not codes(report, family=Family.CORE) - {"CORE_VIEW_UNAVAILABLE"}

    def test_a_core_status_other_than_ok_is_a_warning_and_critical_a_problem(self) -> None:
        assert (
            one(run(obs(core_health=core_health(status="degraded"))), "CORE_STATUS_DEGRADED").severity
            is Severity.WARNING
        )
        assert (
            one(run(obs(core_health=core_health(status="critical"))), "CORE_STATUS_CRITICAL").severity
            is Severity.PROBLEM
        )

    def test_findings_are_counted_and_point_at_the_health_endpoint(self) -> None:
        check = one(run(obs(core_health=core_health(findings=3))), "CORE_FINDINGS")
        assert check.severity is Severity.WARNING
        assert "3" in check.detail
        assert "/api/system/health" in (check.remedy or "")

    def test_a_database_the_core_says_is_down_is_a_problem(self) -> None:
        assert (
            one(run(obs(core_health=core_health(database_up=False))), "CORE_DATABASE_DOWN").severity is Severity.PROBLEM
        )

    def test_no_agent_is_information_because_nobody_attached_the_ea_yet(self) -> None:
        check = one(run(obs(core_health=core_health(agents_connected=0))), "CORE_NO_AGENT")
        assert check.severity is Severity.INFO
        assert "normal" in check.detail

    def test_a_connected_agent_is_counted(self) -> None:
        check = one(run(obs(core_health=core_health(agents_connected=1))), "CORE_AGENT_CONNECTED")
        assert check.severity is Severity.OK

    def test_an_older_core_that_does_not_report_agents_or_workers_is_not_blamed(self) -> None:
        report = run(obs(core_health=core_health()))
        assert one(report, "CORE_AGENTS_UNREPORTED").severity is Severity.INFO
        assert one(report, "MT5_WORKERS_UNREPORTED").severity is Severity.INFO

    @pytest.mark.parametrize(
        ("alive", "code", "severity"),
        [
            (0, "MT5_NO_ACCOUNT", Severity.INFO),
            (1, "MT5_WORKERS_OK", Severity.OK),
            (2, "MT5_WORKERS_EXCESS", Severity.WARNING),
        ],
    )
    def test_the_mt5_workers_are_judged_against_one_account_at_a_time(
        self, alive: int, code: str, severity: Severity
    ) -> None:
        health = core_health(mt5_workers=Mt5WorkersFacts(spawned=15, ended=15 - alive, alive=alive))
        assert one(run(obs(core_health=health)), code).severity is severity

    def test_excess_workers_are_never_to_be_killed_by_hand(self) -> None:
        health = core_health(mt5_workers=Mt5WorkersFacts(spawned=9, ended=7, alive=2))
        assert "ne tuez" in (one(run(obs(core_health=health)), "MT5_WORKERS_EXCESS").remedy or "")

    def test_the_execution_mode_is_shown_when_the_core_reports_it(self) -> None:
        check = one(run(obs(core_health=core_health(execution_mode="OFF"))), "CORE_EXECUTION_MODE")
        assert check.severity is Severity.INFO
        assert "OFF" in check.detail
        assert "CORE_EXECUTION_MODE" not in codes(run())


class TestMetaTraderIsNotInspectedYet:
    def test_the_report_says_so_instead_of_inventing_a_state(self) -> None:
        report = run()
        checks = [c for c in report.checks if c.family is Family.METATRADER]
        assert [c.code for c in checks] == ["MT5_NOT_INSPECTED"]
        assert checks[0].severity is Severity.UNKNOWN

    def test_it_never_claims_an_ea_is_ready_or_a_terminal_connected(self) -> None:
        text = render_doctor(run()).lower()
        assert "ea_ready" not in text
        assert "prêt à exécuter" not in text


class TestEveryFindingTellsWhatToDo:
    SCENARIOS = (
        {"environment": facts(docker=False), "database": ComponentState.UNAVAILABLE},
        {"environment": facts(venv=False, env_file=False, npm=False)},
        {"core": ComponentState.UNHEALTHY},
        {"cockpit": ComponentState.FOREIGN},
        {"database": ComponentState.STARTING},
        {"registry_problem": "illisible"},
        {"core_health": core_health(status="critical", findings=2, database_up=False)},
        {"core_health": core_health(mt5_workers=Mt5WorkersFacts(spawned=5, ended=2, alive=3))},
    )

    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_a_problem_or_a_warning_always_has_a_remedy(self, scenario: dict[str, object]) -> None:
        report = run(obs(**scenario))  # type: ignore[arg-type]
        offenders = [
            c.code for c in report.checks if c.severity in {Severity.PROBLEM, Severity.WARNING} and not c.remedy
        ]
        assert not offenders, offenders


class TestRendering:
    def test_the_text_names_each_family_says_read_only_and_gives_actions(self) -> None:
        text = render_doctor(run(obs(environment=facts(npm=False), core_health=core_health(findings=2))))
        assert "lecture seule" in text
        for family in ("Environnement", "Composants", "Lanceur", "Cœur", "MetaTrader 5"):
            assert family in text
        assert "PROBLÈME" in text and "ATTENTION" in text
        assert "→ action" in text
        assert "Résultat" in text

    def test_a_clean_report_says_nothing_blocks(self) -> None:
        assert "aucun problème" in render_doctor(run()).lower()

    def test_the_document_is_json_serialisable_camel_cased_and_carries_the_verdict(self) -> None:
        document = doctor_document(run(obs(environment=facts(npm=False), core_health=core_health())))
        parsed = json.loads(json.dumps(document))
        assert parsed["ok"] is False
        assert "observedAt" in parsed
        first = parsed["checks"][0]
        assert {"code", "family", "severity", "subject", "detail", "observedAt"} <= set(first)
        assert first["terminalId"] is None and first["accountId"] is None
