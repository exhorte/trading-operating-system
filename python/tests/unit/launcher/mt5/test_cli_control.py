"""``launcher mt5 start | status | verify`` (ADR 0038 § 8, ADR 0039 §§ 3 and 5, I6 and I7). The machine is the fake of ``test_control``: a terminal that obeys a close request (or does not), a
spawner, a probe, the core's answer. Exit codes: 0 fine · 1 refused, blocked or failed · 2 the machine or the core could not be read."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.launcher.mt5.support_control import Machine, ready
from tests.unit.launcher.mt5.support_deploy import TERMINAL_ID
from trading_os.cli.main import main
from trading_os.launcher.mt5 import cli as mt5_cli
from trading_os.launcher.mt5.model import CenterFacts, TerminalSnapshot, TerminalVerdict, VerdictCondition

PHRASE = f"FERMER {TERMINAL_ID}"


def wire(monkeypatch: pytest.MonkeyPatch, machine: Machine) -> None:
    world = machine.world
    monkeypatch.setattr(mt5_cli, "default_config", lambda: world.config)
    monkeypatch.setattr(mt5_cli, "make_files", lambda: world.files)
    monkeypatch.setattr(mt5_cli, "make_registry", lambda cfg: world.registry)
    monkeypatch.setattr(mt5_cli, "make_events", lambda cfg: world.events)
    monkeypatch.setattr(mt5_cli, "make_process_table", lambda: machine.table)
    monkeypatch.setattr(mt5_cli, "make_center_view", lambda cfg: machine.center)
    monkeypatch.setattr(mt5_cli, "make_health", lambda: machine.health)
    monkeypatch.setattr(mt5_cli, "make_spawner", lambda: machine)
    monkeypatch.setattr(mt5_cli, "make_controller_port", lambda: machine)
    monkeypatch.setattr(mt5_cli, "make_sleeper", lambda: machine)
    monkeypatch.setattr(mt5_cli, "make_positions_probe", lambda cfg: machine.probe)


def machine_for(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: object) -> Machine:
    machine = Machine(tmp_path, **kwargs)  # type: ignore[arg-type]
    wire(monkeypatch, machine)
    return machine


def run(*args: str) -> int:
    return main(["launcher", "mt5", *args])


# ------------------------------------------------------------------------------------------------ start


def test_a_dry_run_shows_the_gates_and_starts_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=False)
    assert run("start", "--terminal", TERMINAL_ID, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "AGENT_DEPLOYED" in out and "PRESET_PREPARED" in out and "Simulation" in out
    assert machine.spawned == [] and machine.closed_asked == []


def test_a_closed_terminal_is_started_and_the_agents_hello_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=False)
    machine.center.hello_after(2, ready())
    assert run("start", "--terminal", TERMINAL_ID) == 0
    out = capsys.readouterr().out
    assert "EA_CONNECTED" in out and "hello" in out and "jamais à CONFIRM, ARMED ni AUTONOMOUS" in out
    assert len(machine.spawned) == 1


def test_an_open_terminal_is_not_closed_without_the_flag_and_the_phrase_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    assert run("start", "--terminal", TERMINAL_ID) == 1
    err = capsys.readouterr().err
    assert PHRASE in err and "--confirm-close" in err
    assert machine.closed_asked == [] and machine.spawned == []


def test_an_open_terminal_is_closed_politely_and_restarted_when_the_phrase_is_typed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    machine.center.hello_after(2, ready())
    monkeypatch.setattr("sys.stdin", io.StringIO(PHRASE + "\n"))
    assert run("start", "--terminal", TERMINAL_ID, "--confirm-close") == 0
    assert machine.closed_asked == [1872] and len(machine.spawned) == 1
    assert "fermé poliment, sans arrêt forcé" in capsys.readouterr().out


@pytest.mark.parametrize("typed", ["", "oui\n", "fermer\n", f"{PHRASE} extra\n"])
def test_a_wrong_phrase_closes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, typed: str) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    monkeypatch.setattr("sys.stdin", io.StringIO(typed))
    assert run("start", "--terminal", TERMINAL_ID, "--confirm-close") == 1
    assert machine.closed_asked == [] and machine.spawned == []


def test_a_position_open_blocks_even_the_dry_run_with_a_refusal_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    machine.probe.snapshot = TerminalSnapshot(login="486046157", positions=1, orders=0)
    assert run("start", "--terminal", TERMINAL_ID, "--dry-run") == 1
    out = capsys.readouterr().out
    assert "REFUS" in out and "NO_OPEN_POSITIONS" in out and "Rien n'a été fermé" in out
    assert machine.closed_asked == []


def test_the_command_has_no_way_to_skip_the_confirmation_and_takes_no_secret() -> None:
    from trading_os.cli.main import build_parser

    parser = build_parser()
    options: set[str] = set()

    def collect(p: object) -> None:
        import argparse

        for action in p._actions:  # type: ignore[attr-defined]
            options.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices.values():
                    collect(sub)

    collect(parser)
    assert not {"--yes", "-y", "--force", "--password", "--token"} & options


def test_an_unknown_terminal_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine_for(monkeypatch, tmp_path, running=False)
    assert run("start", "--terminal", "NOPE") == 1
    assert "inconnu" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------------ status and verify


def verdict(**changes: object) -> CenterFacts:
    conditions = (
        VerdictCondition(
            code="TERMINAL_RUNNING", label="Terminal MetaTrader démarré", light="GREEN", detail="le terminal tourne"
        ),
        VerdictCondition(
            code="PRODUCT_IDENTITY", label="Identité du produit", light="RED", detail="aucun produit déclaré"
        ),
    )
    base: dict[str, object] = {
        "verdict": "BLOCKED",
        "red_codes": ("PRODUCT_UNDECLARED",),
        "header_code": "ACCOUNT_IDENTITY_UNVERIFIED",
        "heartbeat_age_s": 3.0,
        "agent_version": "1.13",
        "execution_authorization": "BLOQUÉE — SYSTEM_MODE_OFF",
        "conditions": conditions,
    }
    base.update(changes)
    return CenterFacts(reachable=True, hello_received=True, verdict=TerminalVerdict(**base))  # type: ignore[arg-type]


def test_status_says_the_state_the_reason_and_the_authorization_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    machine.center.facts = verdict()
    assert run("status") == 0
    out = capsys.readouterr().out
    assert "EA_CONNECTED" in out and "hello reçu" in out and "ACCOUNT_IDENTITY_UNVERIFIED" in out
    assert "Execution Authorization" in out and "SYSTEM_MODE_OFF" in out
    assert machine.entry().last_state is not None, "the state was journalled"


def test_status_goes_through_validating_before_blocked_and_never_jumps_to_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    machine.center.facts = verdict(verdict="READY", red_codes=(), header_code=None)
    seen = []
    for _ in range(3):
        assert run("status", "--json") == 0
        seen.append(json.loads(capsys.readouterr().out)[0]["state"])
    assert seen == ["EA_CONNECTED", "EA_VALIDATING", "EA_READY"]


def test_status_without_a_core_says_it_cannot_observe_the_attachment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    machine.center.facts = CenterFacts(reachable=False)
    assert run("status") == 0
    assert "ne répond pas" in capsys.readouterr().out


def test_verify_lists_the_conditions_and_exits_one_when_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    machine.center.facts = verdict()
    assert run("verify", "--terminal", TERMINAL_ID) == 1
    out = capsys.readouterr().out
    assert "[OK     ] Terminal MetaTrader démarré" in out and "[ROUGE  ] Identité du produit" in out
    assert "ligne séparée" in out


def test_verify_exits_zero_when_the_reading_is_ready_and_two_when_the_core_is_silent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    machine.center.facts = verdict(verdict="READY", red_codes=(), header_code=None, conditions=())
    assert run("verify", "--terminal", TERMINAL_ID) == 0
    machine.center.facts = CenterFacts(reachable=False)
    assert run("verify", "--terminal", TERMINAL_ID) == 2
    assert "ne répond pas" in capsys.readouterr().out


def test_status_and_verify_start_nothing_and_close_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    machine = machine_for(monkeypatch, tmp_path, running=True)
    machine.center.facts = verdict()
    run("status")
    run("verify", "--terminal", TERMINAL_ID)
    assert machine.spawned == [] and machine.closed_asked == [] and machine.probe.calls == []


def test_a_fake_namespace_is_not_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert SimpleNamespace  # (kept so the import above documents the style of the other CLI tests)
