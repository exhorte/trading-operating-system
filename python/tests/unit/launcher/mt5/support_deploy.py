"""Builders for the compile / deploy tests (ADR 0039 § 7, I4): a small agent repository on disk, a fake MetaEditor, a terminal data folder under
``tmp_path``. The files are real files in a temporary folder (the deployer writes them for real); what the *machine* says — the origin of a data
folder — comes from the in-memory files port of the other MetaTrader tests."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from tests.unit.launcher.mt5.support import FakeMt5Files, add_install, folder, junction
from tests.unit.launcher.support import T0, FakeProcessTable
from trading_os.launcher.events import EventLog
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.mt5.deploy import EaDeployer
from trading_os.launcher.mt5.manifest import BuildManifest, BuildStore
from trading_os.launcher.mt5.model import DataFolder, EaInstall, EaInstallKind, TerminalEntry, TerminalSource
from trading_os.launcher.mt5.terminals import TerminalRegistry
from trading_os.launcher.ports import CommandResult
from trading_os.shared.time import ManualClock

TERMINAL_ID = "D0E8209F77C8CF37AD8BF550E51FF075"

AGENT_SOURCE = """\
#property version   "1.13"
#define AGENT_VERSION      "1.13"
const ExecutionMode g_mode = MODE_OBSERVE;
const ExecutionMode g_mode_ceiling = MODE_OBSERVE;
input string InpCoreHost       = "127.0.0.1"; // The core's host
input int    InpCorePort       = 9765;        // The core's port
input string InpAccountId         = "";          // OPTIONAL: the login this terminal is expected to be on
input int    InpMagicNumber       = 0;           // REQUIRED: unique per environment
input string InpTradableLogins    = "";          // logins an order may EVER reach
input string InpClosableLogins    = "";          // logins a close may EVER reach
input int    InpHeartbeatSeconds  = 5;
input double InpMaxVolumePerOrder = 1.0;         // lots
input string InpAllowedSymbolsCsv = "XAUUSDm,EURUSDm"; // local whitelist
void Hello() { string json = "\\"agentVersion\\":\\"" + AGENT_VERSION + "\\","; json += "\\"capabilities\\":[\\"ping\\",\\"halt\\",\\"dead_man\\",\\"limit\\",\\"modify\\",\\"close\\",\\"cancel\\"],"; }
"""


def write_agent_repo(repo: Path, *, source: str = AGENT_SOURCE) -> Path:
    agent = repo / "tools" / "mt5-execution-agent"
    (agent / "Include").mkdir(parents=True)
    (agent / "Scripts").mkdir()
    (agent / "TradingOsAgent.mq5").write_text(source, encoding="utf-8")
    (agent / "Include" / "JsonLite.mqh").write_text("// json\n", encoding="utf-8")
    (agent / "Include" / "TradeRequest.mqh").write_text("// requests\n", encoding="utf-8")
    (agent / "Scripts" / "TradingOsRequestCheck.mq5").write_text("// check\n", encoding="utf-8")
    return agent


class FakeEditor:
    """MetaEditor, as far as the builder can tell: it is given ``/compile:`` and ``/log:`` and it leaves a ``.ex5`` and a UTF-16 log."""

    def __init__(self, *, errors: int = 0, warnings: int = 0, produce: bool = True, encoding: str = "utf-16") -> None:
        self.errors = errors
        self.warnings = warnings
        self.produce = produce
        self.encoding = encoding
        self.calls: list[tuple[Sequence[str], float, Path | None]] = []
        self.compiled: list[str] = []  # the source text each compilation was given

    def run(self, args: Sequence[str], *, timeout: float, cwd: Path | None = None) -> CommandResult:
        self.calls.append((list(args), timeout, cwd))
        source = Path(next(a for a in args if a.lower().startswith("/compile:"))[len("/compile:") :])
        log = Path(next(a for a in args if a.lower().startswith("/log:"))[len("/log:") :])
        self.compiled.append(source.read_text(encoding="utf-8"))
        if self.produce and self.errors == 0:
            source.with_suffix(".ex5").write_bytes(b"EX5\x00" + hashlib.sha256(source.read_bytes()).digest() * 8)
        log.write_text(
            f"Result: {self.errors} errors, {self.warnings} warnings, 321 msec elapsed\r\n", encoding=self.encoding
        )
        return CommandResult(1 if self.errors == 0 else 0, "", "")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class World:
    """A repository holding the agent, a terminal data folder, a registry and a deployer, all under one temporary folder."""

    def __init__(self, tmp: Path, *, ea: str = "none") -> None:
        self.tmp = tmp
        self.repo = tmp / "repo"
        self.agent = write_agent_repo(self.repo)
        self.config = LauncherConfig(repo_root=self.repo)
        self.install = tmp / "MetaTrader 5"
        self.install.mkdir()
        (self.install / "terminal64.exe").write_bytes(b"MZ")
        self.data = tmp / "MetaQuotes" / "Terminal" / TERMINAL_ID
        (self.data / "MQL5" / "Experts").mkdir(parents=True)
        (self.data / "MQL5" / "Files").mkdir()
        (self.data / "MQL5" / "Files" / "orders-486046157-486046.dat").write_bytes(b"command store")
        (self.data / "MQL5" / "Files" / "tradingos_agent.token").write_bytes(b"not-a-real-token")
        self.files = FakeMt5Files()
        add_install(self.files, str(self.install))
        self.files.add_dir(str(self.data))
        self.files.origins[_key(str(self.data))] = str(self.install)
        self.clock = ManualClock(T0)
        self.processes = FakeProcessTable([])
        self.registry = TerminalRegistry(self.config.terminals_path, self.clock, self.processes, 4242)
        self.registry.register(
            terminal_id=TERMINAL_ID,
            label="exness-demo",
            install_path=str(self.install),
            data_path=str(self.data),
            portable=False,
            source=TerminalSource.DISCOVERED,
        )
        self.events = EventLog(self.config.events_dir, self.clock)
        self.store = BuildStore(self.config.var_dir / "mt5" / "builds")
        self.deployer = EaDeployer(
            self.files, self.config, self.clock, self.registry, self.events, self.processes, pid=4242
        )
        self.junction_target: Path | None = None
        if ea == "junction":
            self.junction_target = self.repo / "tools" / "mt5-execution-agent"
        elif ea == "directory":
            (self.data / "MQL5" / "Experts" / "TradingOsAgent").mkdir()
            (self.data / "MQL5" / "Experts" / "TradingOsAgent" / "TradingOsAgent.mq5").write_text(
                "// ours", encoding="utf-8"
            )

    # --- the pieces a test combines
    def entry(self) -> TerminalEntry:
        found = self.registry.load().find(TERMINAL_ID)
        assert found is not None
        return found

    def folder(self) -> DataFolder:
        eas: tuple[EaInstall, ...] = ()
        if self.junction_target is not None:
            eas = (EaInstall(kind=EaInstallKind.JUNCTION, name="TradingOsAgent", target=str(self.junction_target)),)
        elif (self.data / "MQL5" / "Experts" / "TradingOsAgent").is_dir():
            eas = (EaInstall(kind=EaInstallKind.DIRECTORY, name="TradingOsAgent"),)
        return DataFolder(terminal_id=TERMINAL_ID, path=str(self.data), eas=eas)

    def built(
        self, manifest_changes: dict[str, object] | None = None, ex5: bytes = b"EX5 build of 1.13"
    ) -> tuple[BuildManifest, Path]:
        """A finished build, saved the way the builder saves one; ``manifest_changes`` lets a test make the manifest lie."""
        from trading_os.launcher.mt5.manifest import CompileSummary, SourceFile, sources_digest

        sources = (SourceFile(path="TradingOsAgent.mq5", sha256=sha(b"src"), size=3),)
        values: dict[str, object] = {
            "agent_version": "1.13",
            "capabilities": ("ping", "halt", "dead_man", "limit", "modify", "close", "cancel"),
            "compiled_mode": "OBSERVE",
            "mode_ceiling": "OBSERVE",
            "sources": sources,
            "sources_sha256": sources_digest(sources),
            "ex5_sha256": sha(ex5),
            "ex5_size": len(ex5),
            "compiled_at": T0,
            "editor_version": "5.0.0.6230",
            "compilation": CompileSummary(errors=0, warnings=0, log_sha256=sha(b"log")),
        }
        values.update(manifest_changes or {})
        manifest = BuildManifest(**values)  # type: ignore[arg-type]
        build_dir = self.store.save(manifest, ex5, "Result: 0 errors, 0 warnings\n")
        return manifest, build_dir / "TradingOsAgent.ex5"

    def tree(self) -> dict[str, str]:
        """Every file under the temporary folder with its digest — to say *what changed*, and that nothing else did."""
        return {
            str(path.relative_to(self.tmp)): sha(path.read_bytes())
            for path in sorted(self.tmp.rglob("*"))
            if path.is_file()
        }


def _key(path: str) -> str:
    from tests.unit.launcher.mt5.support import key

    return key(path)


__all__ = ["AGENT_SOURCE", "TERMINAL_ID", "FakeEditor", "World", "folder", "junction", "re", "sha", "write_agent_repo"]
