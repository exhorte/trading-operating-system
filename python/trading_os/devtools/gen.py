"""``gen-types``: build the application, read its OpenAPI document and its event models, and write ``lib/api/generated.ts``.

The application is built the way a test builds it — a container that is never started, a database URL that is never connected to — so
generating needs no database, no terminal and no secret.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr

from trading_os.app.config import REPO_ROOT, Settings
from trading_os.app.main import create_app
from trading_os.devtools.typescript import generate
from trading_os.shared.events.base import EVENT_REGISTRY

DEFAULT_OUT = REPO_ROOT / "lib" / "api" / "generated.ts"
REF_TEMPLATE = "#/components/schemas/{model}"


def frame_models() -> dict[str, type[BaseModel]]:
    """Frames of the live stream that are not domain events: the snapshot every connection starts with."""
    from trading_os.api.websocket.models import CockpitSnapshot

    return {"system.snapshot": CockpitSnapshot}


def event_schemas() -> dict[str, dict[str, Any]]:
    import trading_os.domain.events  # noqa: F401  (importing registers every event)

    models: dict[str, type[BaseModel]] = {**EVENT_REGISTRY, **frame_models()}
    return {
        wire_type: model.model_json_schema(mode="serialization", by_alias=True, ref_template=REF_TEMPLATE)
        for wire_type, model in models.items()
    }


def build() -> str:
    settings = Settings(_env_file=None, database_url=SecretStr("postgresql://nobody@127.0.0.1:1/none"))
    document = create_app(settings, start_engine=False).openapi()
    return generate(document, event_schemas())


def write(out: Path = DEFAULT_OUT) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    text = build()
    out.write_text(text, encoding="utf-8", newline="\n")
    return len(text.splitlines())


def is_stale(out: Path = DEFAULT_OUT) -> bool:
    return not out.exists() or out.read_text(encoding="utf-8").replace("\r\n", "\n") != build()
