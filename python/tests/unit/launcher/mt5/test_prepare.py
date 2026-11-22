"""Preparing a terminal: its preset in ``MQL5\\Presets`` and the start-up file the launcher keeps (ADR 0039 §§ 4 and 5, I5). Real files in a temporary
folder; the origin of the data folder comes from the in-memory files port. Every refusal is checked to have written nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.launcher.mt5.support import declared, key
from tests.unit.launcher.mt5.support_deploy import TERMINAL_ID, World, sha
from trading_os.launcher.events import EventType
from trading_os.launcher.mt5.model import DeclaredTerminal, OperationKind
from trading_os.launcher.mt5.prepare import PrepareAction, Preparer, PrepareRefused

EX5 = b"EX5 build of 1.13"


def prepared_world(
    tmp_path: Path, *, declaration: DeclaredTerminal | None = None, deploy: bool = True
) -> tuple[World, Preparer]:
    world = World(tmp_path, ea="directory")
    world.registry.declare(TERMINAL_ID, declaration if declaration is not None else declared())
    if deploy:
        manifest, ex5 = world.built(ex5=EX5)
        plan = world.deployer.plan(world.entry(), world.folder(), manifest, ex5)
        world.deployer.apply(plan, ex5, manifest)
    return world, Preparer(
        world.files, world.config, world.clock, world.registry, world.events, world.processes, pid=4242
    )


def changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}


def test_planning_writes_nothing_and_says_what_would_be_written(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path)
    before = world.tree()
    plan = preparer.plan(world.entry())
    assert world.tree() == before
    assert plan.preset_action is PrepareAction.INSTALL and plan.startup_action is PrepareAction.INSTALL
    assert plan.preset_path.endswith(f"TradingOS-{TERMINAL_ID}.set")
    assert plan.expert_path == r"TradingOsAgent\TradingOsAgent"


def test_applying_writes_the_preset_into_presets_and_the_startup_file_into_the_launchers_own_folder(
    tmp_path: Path,
) -> None:
    world, preparer = prepared_world(tmp_path)
    plan = preparer.plan(world.entry())
    record = preparer.apply(plan)
    preset = world.data / "MQL5" / "Presets" / f"TradingOS-{TERMINAL_ID}.set"
    startup = world.config.var_dir / "mt5" / TERMINAL_ID / "startup.ini"
    assert preset.read_bytes().startswith(b"\xff\xfe") and "InpMagicNumber=486046" in preset.read_bytes().decode(
        "utf-16"
    )
    text = startup.read_text(encoding="utf-8")
    assert text.startswith("[StartUp]") and f"ExpertParameters=TradingOS-{TERMINAL_ID}.set" in text
    assert "Expert=TradingOsAgent\\TradingOsAgent" in text and "Symbol=XAUUSDm" in text and "Period=M5" in text
    assert record.preset_sha256 == sha(preset.read_bytes()) and record.startup_sha256 == sha(startup.read_bytes())
    assert world.entry().prepared == record and world.entry().operation.kind is OperationKind.IDLE
    assert world.events.read()[-1].type is EventType.MT5_PRESET_WRITTEN


def test_nothing_but_the_preset_and_the_launchers_own_files_is_written(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path)
    before = world.tree()
    preparer.apply(preparer.plan(world.entry()))
    allowed = (
        str(Path("MetaQuotes/Terminal") / TERMINAL_ID / "MQL5" / "Presets"),
        str(Path("repo") / "var" / "launcher"),
    )
    touched = changed(before, world.tree())
    assert touched and all(name.startswith(allowed) for name in touched), touched
    files = world.data / "MQL5" / "Files"
    assert (files / "orders-486046157-486046.dat").read_bytes() == b"command store"
    assert (files / "tradingos_agent.token").read_bytes() == b"not-a-real-token"


def test_a_preset_that_is_already_right_is_not_written_again(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path)
    preparer.apply(preparer.plan(world.entry()))
    plan = preparer.plan(world.entry())
    assert plan.preset_action is PrepareAction.UNCHANGED and plan.startup_action is PrepareAction.UNCHANGED
    before = world.tree()
    preparer.apply(plan)
    assert not (world.config.var_dir / "backups" / TERMINAL_ID).exists()
    assert not [name for name in changed(before, world.tree()) if "Presets" in name]


def test_a_changed_declaration_replaces_the_preset_and_keeps_the_old_one(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path)
    preparer.apply(preparer.plan(world.entry()))
    world.registry.declare(TERMINAL_ID, declared(magic=486047))
    plan = preparer.plan(world.entry())
    assert plan.preset_action is PrepareAction.REPLACE
    preparer.apply(plan)
    kept = list((world.config.var_dir / "backups" / TERMINAL_ID).glob("*.set"))
    assert len(kept) == 1 and "InpMagicNumber=486046" in kept[0].read_bytes().decode("utf-16")
    new = (world.data / "MQL5" / "Presets" / f"TradingOS-{TERMINAL_ID}.set").read_bytes().decode("utf-16")
    assert "InpMagicNumber=486047" in new


def test_an_incomplete_declaration_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path, declaration=declared(magic=None))
    before = world.tree()
    with pytest.raises(PrepareRefused) as refused:
        preparer.plan(world.entry())
    assert any("magique" in problem for problem in refused.value.problems)
    assert world.tree() == before


def test_a_terminal_where_no_agent_was_deployed_is_refused(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path, deploy=False)
    with pytest.raises(PrepareRefused) as refused:
        preparer.plan(world.entry())
    assert any("deploy" in problem for problem in refused.value.problems)


def test_a_deployed_agent_that_is_no_longer_the_recorded_one_is_refused(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path)
    (world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5").write_bytes(b"someone replaced it")
    with pytest.raises(PrepareRefused) as refused:
        preparer.plan(world.entry())
    assert any("changé" in problem or "disparu" in problem for problem in refused.value.problems)


def test_a_terminal_that_moved_is_not_written(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path)
    world.files.origins[key(str(world.data))] = r"C:\Elsewhere"
    with pytest.raises(PrepareRefused) as refused:
        preparer.plan(world.entry())
    assert any("MT5_TERMINAL_PATH_CHANGED" in problem for problem in refused.value.problems)
    assert not (world.data / "MQL5" / "Presets").exists()


def test_the_lists_of_logins_are_empty_in_what_is_written(tmp_path: Path) -> None:
    world, preparer = prepared_world(tmp_path)
    preparer.apply(preparer.plan(world.entry()))
    text = (world.data / "MQL5" / "Presets" / f"TradingOS-{TERMINAL_ID}.set").read_bytes().decode("utf-16")
    assert "InpTradableLogins=\r\n" in text and "InpClosableLogins=\r\n" in text
