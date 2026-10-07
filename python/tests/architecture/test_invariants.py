"""Architecture invariants (mission § 50), checked structurally so a refactor cannot silently break them:

* the domain is pure (no I/O, no framework, no import from the outer layers);
* `MetaTrader5` is imported in exactly one module, and no order function exists anywhere in the Python core;
* no `if provider == …` outside the provider profiles;
* no model — domain, event or API — has a field that could carry a secret.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from pathlib import Path
from typing import Any

import trading_os
from trading_os.domain.primitives import DomainModel
from trading_os.shared.events.base import EVENT_REGISTRY, Event

PACKAGE_ROOT = Path(trading_os.__file__).parent


def python_files(subdir: str = "") -> list[Path]:
    return sorted(p for p in (PACKAGE_ROOT / subdir).rglob("*.py") if "__pycache__" not in p.parts)


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class TestDomainIsPure:
    OUTER = (
        "trading_os.infrastructure",
        "trading_os.services",
        "trading_os.api",
        "trading_os.app",
        "trading_os.runtime",
    )
    FRAMEWORKS = (
        "fastapi",
        "starlette",
        "uvicorn",
        "psycopg",
        "httpx",
        "keyring",
        "MetaTrader5",
        "asyncpg",
        "requests",
    )

    def test_the_domain_imports_nothing_from_the_outer_layers_or_a_framework(self) -> None:
        offenders = []
        for path in python_files("domain"):
            for module in imports_of(path):
                if module.startswith(self.OUTER) or module.split(".")[0] in self.FRAMEWORKS:
                    offenders.append(f"{path.relative_to(PACKAGE_ROOT)} → {module}")
        assert not offenders, "\n".join(offenders)

    def test_the_domain_does_no_io(self) -> None:
        banned = re.compile(
            r"\b(open\(|socket\.|subprocess\.|asyncio\.open_connection|asyncio\.start_server|requests\.|os\.environ)"
        )
        offenders = [
            str(p.relative_to(PACKAGE_ROOT))
            for p in python_files("domain")
            if banned.search(p.read_text(encoding="utf-8"))
        ]
        assert not offenders, offenders


class TestMt5Boundary:
    def test_metatrader5_is_imported_in_exactly_one_module(self) -> None:
        importers = [
            p.relative_to(PACKAGE_ROOT).as_posix()
            for p in python_files()
            if any(m == "MetaTrader5" or m.startswith("MetaTrader5.") for m in imports_of(p))
        ]
        assert importers == ["infrastructure/mt5/worker.py"]

    def test_no_order_function_of_the_mt5_api_exists_anywhere_in_the_core(self) -> None:
        # The only OrderSend of the repository is the execution agent's (MQL5), behind its compiled mode ceiling.
        forbidden = re.compile(
            r"\b(order_send|order_check|positions_modify|position_close|order_modify|order_cancel)\b"
        )
        offenders = [
            p.relative_to(PACKAGE_ROOT).as_posix()
            for p in python_files()
            if forbidden.search(p.read_text(encoding="utf-8"))
        ]
        assert not offenders, offenders

    def test_the_worker_whitelist_only_reads(self) -> None:
        from trading_os.infrastructure.mt5.protocol import ALLOWED_FUNCTIONS

        assert all(not re.search(r"send|check|modify|close|cancel", name) for name in ALLOWED_FUNCTIONS)


class TestNoProviderConditionals:
    PATTERN = re.compile(r"(==|!=|\bis\b|\bis not\b|\bin\b)\s*\(?\s*(Provider\.|\"(FTMO|EXNESS)\"|'(FTMO|EXNESS)')")

    def test_provider_specific_behaviour_lives_only_in_the_profiles(self) -> None:
        allowed = {"domain/accounts/profiles.py"}
        offenders = []
        for path in python_files():
            rel = path.relative_to(PACKAGE_ROOT).as_posix()
            if rel in allowed:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if self.PATTERN.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{rel}:{number}: {line.strip()}")
        assert not offenders, "\n".join(offenders)


def import_all_modules() -> None:
    for module in pkgutil.walk_packages(trading_os.__path__, prefix="trading_os."):
        if module.name.endswith(".worker") and "mt5" in module.name:
            continue  # importing it would import MetaTrader5 on Windows; the worker is exercised through its process
        importlib.import_module(module.name)


class TestNoSecretCanRideAModel:
    SECRETISH = re.compile(r"password|passwd|secret|api_?key|token|credential", re.IGNORECASE)
    # Names that *describe* a secret without being one.
    ALLOWED = frozenset({"credentials_stored", "credential_store"})

    def all_subclasses(self, base: type[Any]) -> set[type[Any]]:
        found: set[type[Any]] = set()
        for sub in base.__subclasses__():
            found.add(sub)
            found |= self.all_subclasses(sub)
        return found

    def test_no_domain_model_event_or_wire_message_has_a_secret_looking_field(self) -> None:
        import_all_modules()
        from trading_os.infrastructure.mt5.wire import WireMessage

        offenders = []
        for base in (DomainModel, Event, WireMessage):
            for model in self.all_subclasses(base):
                for name in model.model_fields:
                    if self.SECRETISH.search(name) and name not in self.ALLOWED:
                        offenders.append(f"{model.__module__}.{model.__name__}.{name}")
        assert not offenders, offenders

    def test_event_wire_types_are_unique_dotted_and_registered(self) -> None:
        import_all_modules()
        assert EVENT_REGISTRY
        for wire_type, cls in EVENT_REGISTRY.items():
            assert re.fullmatch(r"[a-z]+(\.[a-z_]+)+", wire_type), wire_type
            assert cls.wire_type == wire_type
