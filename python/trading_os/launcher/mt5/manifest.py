"""The manifest of an agent build (ADR 0039 §§ 4 and 7, I4): what was compiled, from which sources, with which result — so that what is deployed to
a terminal can always be compared with what the repository says.

Pure data and a store of finished builds under ``var/launcher/mt5/builds/<version>-<digest>/``. Nothing here compiles or deploys; the facts about the
agent are read from its *source* (its version, the capabilities it announces, the mode it is compiled in), never guessed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from trading_os.domain.primitives import DomainModel

AGENT_SOURCE_NAME = "TradingOsAgent.mq5"
EX5_NAME = "TradingOsAgent.ex5"
MANIFEST_NAME = "manifest.json"
LOG_NAME = "compile.log"
MANIFEST_VERSION = 1

_VERSION = re.compile(r'#define\s+AGENT_VERSION\s+"([^"]+)"')
_CAPABILITIES = re.compile(r'\\"capabilities\\":\[((?:\\"\w+\\",?)*)\]')
_CAPABILITY = re.compile(r'\\"(\w+)\\"')
_MODE = re.compile(r"\bg_mode\s*=\s*MODE_(\w+)")
_CEILING = re.compile(r"\bg_mode_ceiling\s*=\s*MODE_(\w+)")


class AgentSourceFacts(DomainModel):
    agent_version: str | None = None
    capabilities: tuple[str, ...] | None = None
    compiled_mode: str | None = None
    mode_ceiling: str | None = None


def parse_agent_source(text: str) -> AgentSourceFacts:
    """What the agent's source says of itself. A fact the source does not state stays ``None``."""
    version = _VERSION.search(text)
    capabilities = _CAPABILITIES.search(text)
    mode = _MODE.search(text)
    ceiling = _CEILING.search(text)
    return AgentSourceFacts(
        agent_version=version.group(1) if version else None,
        capabilities=tuple(_CAPABILITY.findall(capabilities.group(1))) if capabilities else None,
        compiled_mode=mode.group(1) if mode else None,
        mode_ceiling=ceiling.group(1) if ceiling else None,
    )


class SourceFile(DomainModel):
    path: str
    sha256: str
    size: int


class CompileSummary(DomainModel):
    errors: int
    warnings: int
    log_sha256: str


class BuildManifest(DomainModel):
    manifest_version: int = MANIFEST_VERSION
    agent_version: str
    capabilities: tuple[str, ...] | None = None
    compiled_mode: str
    mode_ceiling: str
    sources: tuple[SourceFile, ...]
    sources_sha256: str
    ex5_sha256: str
    ex5_size: int
    compiled_at: datetime
    editor_version: str | None = None
    compilation: CompileSummary

    @property
    def build_name(self) -> str:
        return f"{self.agent_version}-{self.ex5_sha256[:8]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sources_digest(files: Sequence[SourceFile]) -> str:
    """One digest of all the sources: the path and the digest of each, in path order."""
    return sha256_bytes(
        "\n".join(f"{item.path}:{item.sha256}" for item in sorted(files, key=lambda f: f.path)).encode()
    )


class BuildStore:
    """The finished builds. A build is a folder: the ``.ex5``, its manifest and the compiler's log."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        return self._directory

    def save(self, manifest: BuildManifest, ex5: bytes, log_text: str) -> Path:
        folder = self._directory / manifest.build_name
        folder.mkdir(parents=True, exist_ok=True)
        self._write(folder / EX5_NAME, ex5)
        self._write(folder / LOG_NAME, log_text.encode("utf-8"))
        document = json.dumps(manifest.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False)
        self._write(
            folder / MANIFEST_NAME, document.encode("utf-8")
        )  # last: a folder with a manifest is a complete build
        return folder

    def latest(self) -> tuple[BuildManifest, Path] | None:
        """The most recent complete build and the path of its ``.ex5``; a folder with a damaged manifest is not trusted."""
        found: list[tuple[BuildManifest, Path]] = []
        if self._directory.is_dir():
            for folder in sorted(self._directory.iterdir()):
                loaded = self.load(folder)
                if loaded is not None:
                    found.append(loaded)
        return max(found, key=lambda item: (item[0].compiled_at, item[1].parent.name)) if found else None

    def load(self, folder: Path) -> tuple[BuildManifest, Path] | None:
        manifest_path = folder / MANIFEST_NAME
        ex5 = folder / EX5_NAME
        if not manifest_path.is_file() or not ex5.is_file():
            return None
        try:
            manifest = BuildManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError):
            return None
        return manifest, ex5

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
