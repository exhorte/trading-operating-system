"""Compiling the agent on a copy (ADR 0039 § 7, I4, and the rule kept since 2026-11-03: never inside the repository's agent folder).

The sources are copied into a working folder of the launcher, MetaEditor is asked to compile *that* copy, the result is read from its log (UTF-16)
and from the file it leaves — never from its exit code — and the build is kept with a manifest. The repository's source stays compiled in ``OBSERVE``
(a source that is not is never built). Since ADR 0043 a ``CONFIRM`` build can be asked for: the two compile-time constants are rewritten **on the copy
only**, so the agent can send an order; whether it ever does is then decided by its preset (the list of tradable logins, empty by default) and the core's ladder.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from trading_os.launcher.events import EventLog, EventSeverity, EventType, new_correlation_id
from trading_os.launcher.model import LauncherConfig
from trading_os.launcher.mt5.manifest import (
    AGENT_SOURCE_NAME,
    EX5_NAME,
    LOG_NAME,
    BuildManifest,
    BuildStore,
    CompileSummary,
    SourceFile,
    parse_agent_source,
    sha256_bytes,
    sources_digest,
)
from trading_os.launcher.ports import CommandRunner
from trading_os.shared.agent_compat import assess_agent
from trading_os.shared.time import Clock

COMPILE_TIMEOUT_S = 180.0
BUILD_MODES = ("OBSERVE", "CONFIRM")
_CONST_MODE = re.compile(r"(const\s+ExecutionMode\s+(?:g_mode|g_mode_ceiling)\s*=\s*)MODE_OBSERVE(\s*;)")
_RESULT = re.compile(r"(\d+)\s+errors?,\s*(\d+)\s+warnings?", re.IGNORECASE)


class BuildRefused(Exception):
    """A build that is not made, with every reason (French: shown to a person)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


@dataclass(frozen=True)
class BuildResult:
    manifest: BuildManifest
    ex5_path: Path


def read_log(data: bytes) -> str:
    """MetaEditor writes its log in UTF-16 with a byte-order mark; anything else is read as UTF-8 so that a test or a future build does not fail on it."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8-sig", errors="replace")


class AgentBuilder:
    def __init__(self, config: LauncherConfig, runner: CommandRunner, clock: Clock, events: EventLog) -> None:
        self._config = config
        self._runner = runner
        self._clock = clock
        self._events = events

    @property
    def source_dir(self) -> Path:
        return self._config.repo_root / "tools" / "mt5-execution-agent"

    @property
    def store(self) -> BuildStore:
        return BuildStore(self._config.var_dir / "mt5" / "builds")

    def build(self, editor_exe: str, *, editor_version: str | None = None, mode: str = "OBSERVE") -> BuildResult:
        correlation = new_correlation_id()
        try:
            result = self._build(editor_exe, editor_version, mode)
        except BuildRefused as refused:
            self._events.emit(
                EventType.MT5_EA_BUILD_REFUSED,
                component="mt5",
                correlation_id=correlation,
                severity=EventSeverity.WARNING,
                diagnostic="; ".join(refused.problems),
            )
            raise
        self._events.emit(
            EventType.MT5_EA_BUILT,
            component="mt5",
            correlation_id=correlation,
            diagnostic=f"agent {result.manifest.agent_version} compilé sur une copie, empreinte {result.manifest.ex5_sha256[:12]}",
        )
        return result

    # ------------------------------------------------------------------------------------------------ internals

    def _build(self, editor_exe: str, editor_version: str | None, mode: str = "OBSERVE") -> BuildResult:
        main = self.source_dir / AGENT_SOURCE_NAME
        if not main.is_file():
            raise BuildRefused([f"la source de l'agent est introuvable : {main}"])
        text = main.read_text(encoding="utf-8", errors="replace")
        facts = parse_agent_source(text)
        problems: list[str] = []
        if not facts.agent_version:
            problems.append("la version de l'agent est illisible dans sa source (AGENT_VERSION)")
        if facts.compiled_mode != "OBSERVE":
            problems.append(
                f"le mode compilé de l'agent est {facts.compiled_mode or 'inconnu'} : le lanceur ne construit que des agents compilés en OBSERVE"
            )
        if facts.mode_ceiling != "OBSERVE":
            problems.append(
                f"le plafond de mode compilé est {facts.mode_ceiling or 'inconnu'} : le lanceur ne construit que des agents au plafond OBSERVE"
            )
        if facts.agent_version:
            compat = assess_agent(facts.agent_version, facts.capabilities, None)
            if not compat.compatible:
                problems.extend(compat.reasons)
        if mode not in BUILD_MODES:
            problems.append(f"mode de compilation inconnu : {mode} (OBSERVE ou CONFIRM)")
        built_text, built_facts = text, facts
        if mode == "CONFIRM" and not problems:
            built_text, rewritten = _CONST_MODE.subn(r"\g<1>MODE_CONFIRM\g<2>", text)
            if rewritten != 2:
                problems.append(
                    "les deux constantes de mode (g_mode, g_mode_ceiling) n'ont pas été trouvées une fois chacune : rien n'est compilé"
                )
            built_facts = parse_agent_source(built_text)
        if problems:
            raise BuildRefused(problems)

        include = sorted((self.source_dir / "Include").glob("*.mqh")) if (self.source_dir / "Include").is_dir() else []
        stamp = self._clock.now().strftime("%Y%m%dT%H%M%S")
        work = self._config.var_dir / "mt5" / "work" / f"build-{stamp}-{new_correlation_id()[:6]}"
        try:
            (work / "Include").mkdir(parents=True)
            (work / AGENT_SOURCE_NAME).write_text(
                built_text, encoding="utf-8"
            )  # the copy: rewritten for a CONFIRM build, never the repository
            for header in include:
                shutil.copy2(header, work / "Include" / header.name)
            log_path = work / LOG_NAME
            self._runner.run(
                [editor_exe, f"/compile:{work / AGENT_SOURCE_NAME}", f"/log:{log_path}"],
                timeout=COMPILE_TIMEOUT_S,
                cwd=work,
            )
            log_bytes = log_path.read_bytes() if log_path.is_file() else b""
            log_text = read_log(log_bytes)
            counts = _RESULT.findall(log_text)
            if not counts:
                raise BuildRefused(
                    ["le journal de compilation ne dit pas combien d'erreurs il y a : compilation non fiable"]
                )
            errors, warnings = int(counts[-1][0]), int(counts[-1][1])
            if errors:
                raise BuildRefused([f"la compilation a produit {errors} erreur(s) : rien n'est gardé"])
            ex5 = work / EX5_NAME
            if not ex5.is_file() or ex5.stat().st_size == 0:
                raise BuildRefused(["la compilation n'a laissé aucun fichier .ex5"])
            ex5_bytes = ex5.read_bytes()
            sources = tuple(
                SourceFile(path=name, sha256=sha256_bytes(content), size=len(content))
                for name, content in (
                    (AGENT_SOURCE_NAME, main.read_bytes()),
                    *((f"Include/{header.name}", header.read_bytes()) for header in include),
                )
            )
            manifest = BuildManifest(
                agent_version=facts.agent_version or "",
                capabilities=facts.capabilities,
                compiled_mode=built_facts.compiled_mode or "",
                mode_ceiling=built_facts.mode_ceiling or "",
                sources=sources,
                sources_sha256=sources_digest(sources),
                ex5_sha256=sha256_bytes(ex5_bytes),
                ex5_size=len(ex5_bytes),
                compiled_at=self._clock.now(),
                editor_version=editor_version,
                compilation=CompileSummary(errors=errors, warnings=warnings, log_sha256=sha256_bytes(log_bytes)),
            )
            folder = self.store.save(manifest, ex5_bytes, log_text)
            return BuildResult(manifest=manifest, ex5_path=folder / EX5_NAME)
        finally:
            shutil.rmtree(work, ignore_errors=True)
