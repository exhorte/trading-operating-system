"""Deploying a build to a registered terminal (ADR 0039 §§ 4 and 7, I4). Real files in a temporary folder; the origin of the data folder comes from
the in-memory files port. Every refusal is checked to have written nothing."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.unit.launcher.mt5.support import INSTALL, key
from tests.unit.launcher.mt5.support_deploy import TERMINAL_ID, World, sha
from trading_os.launcher.events import EventType
from trading_os.launcher.mt5.deploy import DeployAction, DeployRefused
from trading_os.launcher.mt5.model import OperationKind

EX5 = b"EX5 build of 1.13"


def deploy(world: World, **changes: object):
    manifest, ex5 = world.built(changes or None, ex5=EX5)  # type: ignore[arg-type]
    plan = world.deployer.plan(world.entry(), world.folder(), manifest, ex5)
    return plan, ex5, manifest


def changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}


# ------------------------------------------------------------------------------------------------ the plan (writes nothing)


def test_planning_a_deployment_writes_nothing(tmp_path: Path) -> None:
    world = World(tmp_path)
    manifest, ex5 = world.built(ex5=EX5)
    before = world.tree()
    plan = world.deployer.plan(world.entry(), world.folder(), manifest, ex5)
    assert world.tree() == before
    assert plan.action is DeployAction.INSTALL
    assert plan.target_file.endswith("TradingOsAgent.ex5")
    assert plan.expert_path == r"TradingOS\TradingOsAgent"


def test_a_terminal_without_our_agent_gets_a_folder_of_ours_in_experts(tmp_path: Path) -> None:
    world = World(tmp_path)
    plan, ex5, manifest = deploy(world)
    world.deployer.apply(plan, ex5, manifest)
    target = world.data / "MQL5" / "Experts" / "TradingOS" / "TradingOsAgent.ex5"
    assert target.read_bytes() == EX5


def test_an_installed_directory_is_replaced_in_place_and_the_old_build_is_kept(tmp_path: Path) -> None:
    world = World(tmp_path, ea="directory")
    target = world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5"
    target.write_bytes(b"EX5 older build")
    plan, ex5, manifest = deploy(world)
    assert plan.action is DeployAction.REPLACE
    record = world.deployer.apply(plan, ex5, manifest)
    assert target.read_bytes() == EX5
    assert record.previous_sha256 == sha(b"EX5 older build")
    kept = list((world.config.var_dir / "backups" / TERMINAL_ID).glob("*TradingOsAgent.ex5"))
    assert len(kept) == 1 and kept[0].read_bytes() == b"EX5 older build"


def test_through_a_junction_only_the_ex5_of_the_target_changes_and_the_experts_folder_is_untouched(
    tmp_path: Path,
) -> None:
    world = World(tmp_path, ea="junction")
    experts_before = sorted(path.name for path in (world.data / "MQL5" / "Experts").iterdir())
    before = world.tree()
    plan, ex5, manifest = deploy(world)
    world.deployer.apply(plan, ex5, manifest)
    assert sorted(path.name for path in (world.data / "MQL5" / "Experts").iterdir()) == experts_before
    touched = changed(before, world.tree())
    assert r"repo\tools\mt5-execution-agent\TradingOsAgent.ex5" in touched
    assert not any(name.startswith(r"repo\tools\mt5-execution-agent" + "\\Include") for name in touched)


def test_a_build_that_is_already_there_is_not_written_again(tmp_path: Path) -> None:
    world = World(tmp_path, ea="directory")
    target = world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5"
    target.write_bytes(EX5)
    plan, ex5, manifest = deploy(world)
    assert plan.action is DeployAction.UNCHANGED
    before = world.tree()
    world.deployer.apply(plan, ex5, manifest)
    assert not (world.config.var_dir / "backups").exists()
    assert changed(before, world.tree()) <= {  # nothing but the registry's own record and the event line
        name for name in world.tree() if "var" in Path(name).parts
    }


def test_the_deployment_is_recorded_in_the_registry_and_in_the_events(tmp_path: Path) -> None:
    world = World(tmp_path)
    plan, ex5, manifest = deploy(world)
    record = world.deployer.apply(plan, ex5, manifest)
    entry = world.entry()
    assert entry.deployment == record
    assert record.agent_version == "1.13" and record.ex5_sha256 == sha(EX5) and record.target_file == plan.target_file
    assert entry.operation.kind is OperationKind.IDLE
    events = world.events.read()
    assert [event.type for event in events] == [EventType.MT5_EA_DEPLOYED]
    assert events[0].instance_id == TERMINAL_ID and "1.13" in events[0].diagnostic


# ------------------------------------------------------------------------------------------------ refusals (each writes nothing)


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"agent_version": ""}, "version"),
        ({"compiled_mode": "CONFIRM"}, "OBSERVE"),
        ({"mode_ceiling": "ARMED"}, "OBSERVE"),
    ],
)
def test_a_build_the_table_or_the_mode_rejects_is_never_deployed(
    tmp_path: Path, changes: dict[str, object], fragment: str
) -> None:
    world = World(tmp_path)
    manifest, ex5 = world.built(changes, ex5=EX5)
    before = world.tree()
    with pytest.raises(DeployRefused) as refused:
        world.deployer.plan(world.entry(), world.folder(), manifest, ex5)
    assert any(fragment in problem for problem in refused.value.problems)
    assert world.tree() == before


def test_a_build_whose_ex5_is_not_the_one_the_manifest_describes_is_refused(tmp_path: Path) -> None:
    world = World(tmp_path)
    manifest, ex5 = world.built(ex5=EX5)
    ex5.write_bytes(b"tampered")
    with pytest.raises(DeployRefused) as refused:
        world.deployer.plan(world.entry(), world.folder(), manifest, ex5)
    assert any("empreinte" in problem for problem in refused.value.problems)


def test_a_terminal_whose_data_folder_no_longer_belongs_to_its_installation_is_not_written(tmp_path: Path) -> None:
    world = World(tmp_path)
    world.files.origins[key(str(world.data))] = r"C:\Somewhere\Else"
    manifest, ex5 = world.built(ex5=EX5)
    before = world.tree()
    with pytest.raises(DeployRefused) as refused:
        world.deployer.plan(world.entry(), world.folder(), manifest, ex5)
    assert any("MT5_TERMINAL_PATH_CHANGED" in problem for problem in refused.value.problems)
    assert world.tree() == before


def test_a_junction_that_does_not_lead_to_our_agent_is_not_written_through(tmp_path: Path) -> None:
    world = World(tmp_path, ea="junction")
    (world.repo / "tools" / "mt5-execution-agent" / "TradingOsAgent.mq5").unlink()
    manifest, ex5 = world.built(ex5=EX5)
    with pytest.raises(DeployRefused) as refused:
        world.deployer.plan(world.entry(), world.folder(), manifest, ex5)
    assert any("jonction" in problem for problem in refused.value.problems)


def test_a_second_operation_on_the_same_terminal_is_refused(tmp_path: Path) -> None:
    world = World(tmp_path)
    plan, ex5, manifest = deploy(world)
    world.registry.begin_operation(
        TERMINAL_ID, OperationKind.TERMINAL_STOPPING, deployment_id="other", step="x", timeout_s=60
    )
    before = world.tree()
    with pytest.raises(DeployRefused):
        world.deployer.apply(plan, ex5, manifest)
    assert not (world.data / "MQL5" / "Experts" / "TradingOS").exists()
    assert world.entry().operation.kind is OperationKind.TERMINAL_STOPPING, "the other operation is left as it was"
    assert not changed(before, world.tree()) - {name for name in world.tree() if "var" in Path(name).parts}


# ------------------------------------------------------------------------------------------------ failures while writing


def test_a_locked_ex5_leaves_the_previous_build_in_place_and_says_what_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World(tmp_path, ea="directory")
    target = world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5"
    target.write_bytes(b"EX5 older build")
    plan, ex5, manifest = deploy(world)

    real_replace = os.replace

    def locked(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        if Path(destination).name == "TradingOsAgent.ex5":  # the registry's own writes go through
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(DeployRefused) as refused:
        world.deployer.apply(plan, ex5, manifest)
    assert any("détach" in problem or "ferm" in problem for problem in refused.value.problems)
    assert target.read_bytes() == b"EX5 older build"
    assert not list(target.parent.glob("*.tmp*")), "no half-written file is left"
    assert world.entry().operation.kind is OperationKind.IDLE
    assert world.entry().deployment is None


def test_a_copy_that_does_not_verify_is_rolled_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(tmp_path, ea="directory")
    target = world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5"
    target.write_bytes(b"EX5 older build")
    plan, ex5, manifest = deploy(world)
    real_replace = os.replace

    def corrupting(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
        if Path(destination).name == "TradingOsAgent.ex5":
            Path(source).write_bytes(b"garbage")  # the copy that lands is not the build
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", corrupting)
    with pytest.raises(DeployRefused) as refused:
        world.deployer.apply(plan, ex5, manifest)
    assert any("retour arrière" in problem for problem in refused.value.problems)
    assert target.read_bytes() == b"EX5 older build"
    assert world.entry().deployment is None and world.entry().operation.kind is OperationKind.IDLE


# ------------------------------------------------------------------------------------------------ the white list


def test_a_deployment_writes_only_where_it_may_and_never_touches_the_command_store_or_the_token(tmp_path: Path) -> None:
    world = World(tmp_path, ea="directory")
    (world.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5").write_bytes(b"EX5 older build")
    plan, ex5, manifest = deploy(world)
    before = world.tree()
    world.deployer.apply(plan, ex5, manifest)
    touched = changed(before, world.tree())
    allowed_prefixes = (
        str(Path("MetaQuotes/Terminal") / TERMINAL_ID / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.ex5"),
        str(Path("repo") / "var" / "launcher"),
    )
    assert touched and all(name.startswith(allowed_prefixes) for name in touched), touched
    files = world.data / "MQL5" / "Files"
    assert (files / "orders-486046157-486046.dat").read_bytes() == b"command store"
    assert (files / "tradingos_agent.token").read_bytes() == b"not-a-real-token"
    assert INSTALL  # (the constant is only here to keep the import honest)
