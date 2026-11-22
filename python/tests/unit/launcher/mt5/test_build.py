"""Compiling the agent on a copy and writing its manifest (ADR 0039 § 7, I4). Nothing here runs MetaEditor: a fake leaves the files it would leave."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.launcher.mt5.support_deploy import AGENT_SOURCE, FakeEditor, sha, write_agent_repo
from tests.unit.launcher.support import T0
from trading_os.launcher.events import EventLog
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.mt5.build import AgentBuilder, BuildRefused
from trading_os.launcher.mt5.manifest import BuildStore, parse_agent_source
from trading_os.shared.time import ManualClock

EDITOR = r"C:\Program Files\MetaTrader 5\metaeditor64.exe"
REAL_SOURCE = Path(__file__).resolve().parents[5] / "tools" / "mt5-execution-agent" / "TradingOsAgent.mq5"


def tree(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha(path.read_bytes()) for path in sorted(root.rglob("*")) if path.is_file()}


def builder(tmp_path: Path, editor: FakeEditor, source: str = AGENT_SOURCE) -> tuple[AgentBuilder, LauncherConfig]:
    write_agent_repo(tmp_path / "repo", source=source)
    config = LauncherConfig(repo_root=tmp_path / "repo")
    clock = ManualClock(T0)
    return AgentBuilder(config, editor, clock, EventLog(config.events_dir, clock)), config


# ------------------------------------------------------------------------------------------------ reading the source


def test_the_facts_of_the_real_agent_source_are_read_without_compiling() -> None:
    facts = parse_agent_source(REAL_SOURCE.read_text(encoding="utf-8"))
    assert facts.agent_version and facts.agent_version.count(".") == 1
    assert facts.capabilities and "dead_man" in facts.capabilities and "ping" in facts.capabilities
    assert facts.compiled_mode == "OBSERVE"
    assert facts.mode_ceiling == "OBSERVE"


def test_a_source_without_the_facts_gives_none_never_a_guess() -> None:
    facts = parse_agent_source("// nothing here")
    assert facts.agent_version is None
    assert facts.capabilities is None
    assert facts.compiled_mode is None


# ------------------------------------------------------------------------------------------------ the build


def test_a_build_compiles_a_copy_and_keeps_the_source_folder_as_it_was(tmp_path: Path) -> None:
    editor = FakeEditor()
    agent, config = builder(tmp_path, editor)
    before = tree(tmp_path / "repo" / "tools")
    result = agent.build(EDITOR, editor_version="5.0.0.6230")
    assert tree(tmp_path / "repo" / "tools") == before  # no .ex5, no log, nothing inside the repository's agent folder
    (args, timeout, _cwd) = editor.calls[0]
    compiled = Path(next(a for a in args if a.startswith("/compile:"))[len("/compile:") :])
    assert (
        args[0] == EDITOR
        and "work" in compiled.parts
        and compiled.parent != tmp_path / "repo" / "tools" / "mt5-execution-agent"
    )
    assert timeout > 0
    manifest = result.manifest
    assert manifest.agent_version == "1.13"
    assert manifest.compiled_mode == "OBSERVE"
    assert manifest.capabilities and "dead_man" in manifest.capabilities
    assert manifest.compilation.errors == 0 and manifest.editor_version == "5.0.0.6230"
    assert {item.path for item in manifest.sources} == {
        "TradingOsAgent.mq5",
        "Include/JsonLite.mqh",
        "Include/TradeRequest.mqh",
    }
    assert all(len(item.sha256) == 64 for item in manifest.sources)
    assert result.ex5_path.read_bytes() and sha(result.ex5_path.read_bytes()) == manifest.ex5_sha256
    assert result.ex5_path.parent.parent == config.var_dir / "mt5" / "builds"
    assert not list((config.var_dir / "mt5" / "work").glob("*")), "the working copy is removed"


def test_the_manifest_digest_of_the_sources_changes_with_a_single_byte(tmp_path: Path) -> None:
    first, _ = builder(tmp_path / "a", FakeEditor())
    second, _ = builder(tmp_path / "b", FakeEditor(), source=AGENT_SOURCE + "// one more line\n")
    assert first.build(EDITOR).manifest.sources_sha256 != second.build(EDITOR).manifest.sources_sha256


def test_the_log_is_read_in_utf16_the_way_metaeditor_writes_it(tmp_path: Path) -> None:
    agent, _ = builder(tmp_path, FakeEditor(warnings=2, encoding="utf-16"))
    assert agent.build(EDITOR).manifest.compilation.warnings == 2


def test_a_build_with_errors_is_refused_and_nothing_is_kept(tmp_path: Path) -> None:
    agent, config = builder(tmp_path, FakeEditor(errors=3))
    with pytest.raises(BuildRefused) as refused:
        agent.build(EDITOR)
    assert any("3" in problem and "erreur" in problem for problem in refused.value.problems)
    assert (
        not list((config.var_dir / "mt5" / "builds").glob("*"))
        if (config.var_dir / "mt5" / "builds").exists()
        else True
    )


def test_a_compile_that_leaves_no_ex5_is_refused(tmp_path: Path) -> None:
    agent, _ = builder(tmp_path, FakeEditor(produce=False))
    with pytest.raises(BuildRefused) as refused:
        agent.build(EDITOR)
    assert any(".ex5" in problem for problem in refused.value.problems)


def test_a_source_that_is_not_compiled_in_observe_is_never_built(tmp_path: Path) -> None:
    confirm = AGENT_SOURCE.replace("g_mode = MODE_OBSERVE", "g_mode = MODE_CONFIRM")
    editor = FakeEditor()
    agent, _ = builder(tmp_path, editor, source=confirm)
    with pytest.raises(BuildRefused) as refused:
        agent.build(EDITOR)
    assert any("OBSERVE" in problem for problem in refused.value.problems)
    assert not editor.calls, "the editor is not even started"


def test_a_confirm_build_rewrites_the_two_constants_on_the_copy_only(tmp_path: Path) -> None:
    """ADR 0043: the launcher can make an agent able to send an order; the repository's source stays compiled in OBSERVE."""
    editor = FakeEditor()
    agent, _ = builder(tmp_path, editor)
    source = tmp_path / "repo" / "tools" / "mt5-execution-agent" / "TradingOsAgent.mq5"
    before = source.read_text(encoding="utf-8")
    manifest = agent.build(EDITOR, mode="CONFIRM").manifest
    assert (manifest.compiled_mode, manifest.mode_ceiling) == ("CONFIRM", "CONFIRM")
    compiled = editor.compiled[0]
    assert "g_mode = MODE_CONFIRM;" in compiled and "g_mode_ceiling = MODE_CONFIRM;" in compiled
    assert "MODE_OBSERVE;" not in compiled.split("enum", 1)[-1].split("}", 1)[-1]
    assert source.read_text(encoding="utf-8") == before  # the repository is never rewritten


def test_an_observe_build_stays_the_default(tmp_path: Path) -> None:
    editor = FakeEditor()
    agent, _ = builder(tmp_path, editor)
    assert agent.build(EDITOR).manifest.compiled_mode == "OBSERVE"
    assert "g_mode = MODE_OBSERVE;" in editor.compiled[0]


def test_an_unknown_build_mode_is_refused_before_the_editor_starts(tmp_path: Path) -> None:
    editor = FakeEditor()
    agent, _ = builder(tmp_path, editor)
    with pytest.raises(BuildRefused) as refused:
        agent.build(EDITOR, mode="AUTONOMOUS")
    assert any("mode de compilation inconnu" in problem for problem in refused.value.problems) and not editor.calls


def test_a_source_with_no_readable_version_is_never_built(tmp_path: Path) -> None:
    agent, _ = builder(tmp_path, FakeEditor(), source="// nothing\n")
    with pytest.raises(BuildRefused):
        agent.build(EDITOR)


def test_a_missing_agent_folder_is_a_refusal_not_a_crash(tmp_path: Path) -> None:
    config = LauncherConfig(repo_root=tmp_path / "empty")
    clock = ManualClock(T0)
    with pytest.raises(BuildRefused):
        AgentBuilder(config, FakeEditor(), clock, EventLog(config.events_dir, clock)).build(EDITOR)


# ------------------------------------------------------------------------------------------------ the store


def test_the_store_gives_back_the_latest_build(tmp_path: Path) -> None:
    agent, config = builder(tmp_path, FakeEditor())
    store = BuildStore(config.var_dir / "mt5" / "builds")
    assert store.latest() is None
    first = agent.build(EDITOR).manifest
    latest = store.latest()
    assert latest is not None and latest[0] == first
    assert latest[1].name == "TradingOsAgent.ex5" and latest[1].exists()


def test_a_damaged_manifest_is_skipped_not_trusted(tmp_path: Path) -> None:
    agent, config = builder(tmp_path, FakeEditor())
    result = agent.build(EDITOR)
    (result.ex5_path.parent / "manifest.json").write_text("{ not json", encoding="utf-8")
    assert BuildStore(config.var_dir / "mt5" / "builds").latest() is None
