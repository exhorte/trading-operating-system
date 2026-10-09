"""Architecture invariants (mission § 50), checked structurally so a refactor cannot silently break them:

* the domain is pure (no I/O, no framework, no import from the outer layers);
* `MetaTrader5` is imported in exactly one module, and no order function exists anywhere in the Python core;
* no `if provider == …` outside the provider profiles;
* no model — domain, event or API — has a field that could carry a secret, except the ``…Request`` models through which a
  password *arrives* (typed ``SecretStr``) and the settings: a secret travels in one direction, and never out.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel, SecretStr

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


class TestSecretsTravelInOneDirection:
    """A password can come *in* — a ``…Request`` model of the API, typed ``SecretStr`` — and cannot go *out*: no response of the
    OpenAPI document reaches a secret-looking property or a write-only value."""

    SECRETISH = TestNoSecretCanRideAModel.SECRETISH
    ALLOWED = TestNoSecretCanRideAModel.ALLOWED

    @staticmethod
    def is_secret_str(annotation: Any) -> bool:
        return annotation is SecretStr or any(arg is SecretStr for arg in get_args(annotation))

    def secret_fields(self) -> Iterator[tuple[type[BaseModel], str, Any]]:
        import_all_modules()
        for model in TestNoSecretCanRideAModel().all_subclasses(BaseModel):
            if not model.__module__.startswith("trading_os."):
                continue
            for name, field in model.model_fields.items():
                if self.SECRETISH.search(name) and name not in self.ALLOWED:
                    yield model, name, field.annotation

    def test_a_secret_is_a_secret_str_in_a_request_model_of_the_api_or_in_the_settings(self) -> None:
        from trading_os.api.schemas.accounts import SecretRequest
        from trading_os.app.config import Settings

        offenders = []
        for model, name, annotation in self.secret_fields():
            where = f"{model.__module__}.{model.__name__}.{name}"
            home = model is Settings or (
                model.__module__.startswith("trading_os.api.schemas")
                and model.__name__.endswith("Request")
                and issubclass(model, SecretRequest)
            )
            if not home:
                offenders.append(f"{where}: only a ...Request model of the API (or the settings) may carry a secret")
            elif not self.is_secret_str(annotation):
                offenders.append(f"{where}: must be typed SecretStr")
        assert not offenders, "\n".join(offenders)

    def test_no_response_of_the_api_reaches_a_secret(self) -> None:
        from trading_os.app.config import Settings
        from trading_os.app.main import create_app

        settings = Settings(_env_file=None, database_url=SecretStr("postgresql://nobody@127.0.0.1:1/none"))
        document = create_app(settings, start_engine=False).openapi()
        components = document["components"]["schemas"]

        offenders: list[str] = []

        def walk(node: Any, trail: str, seen: set[str]) -> None:
            if isinstance(node, list):
                for item in node:
                    walk(item, trail, seen)
            elif isinstance(node, dict):
                if node.get("writeOnly") or node.get("format") == "password":
                    offenders.append(f"{trail}: a write-only value in a response")
                reference = node.get("$ref")
                if reference:
                    name = reference.rsplit("/", 1)[-1]
                    if name not in seen:
                        walk(components[name], f"{trail}>{name}", seen | {name})
                for key, value in node.get("properties", {}).items():
                    if self.SECRETISH.search(key) and key not in self.ALLOWED:
                        offenders.append(f"{trail}.{key}: a secret-looking property in a response")
                    walk(value, f"{trail}.{key}", seen)
                for key in ("items", "additionalProperties", "anyOf", "oneOf", "allOf", "prefixItems"):
                    if key in node:
                        walk(node[key], trail, seen)

        for path, operations in document["paths"].items():
            for method, operation in operations.items():
                for status, response in operation.get("responses", {}).items():
                    for media in response.get("content", {}).values():
                        walk(media.get("schema", {}), f"{method.upper()} {path} -> {status}", set())
        assert not offenders, "\n".join(offenders)
