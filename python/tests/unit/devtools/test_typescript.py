"""The TypeScript generator: how it renders each construct, what it refuses, and that the committed file is the one the core would write
today. No database, no terminal: it builds the application the way a test does."""

from __future__ import annotations

import re
from typing import Any

import pytest

from trading_os.api.routes.strategy import MAX_LOOKBACK
from trading_os.app.config import REPO_ROOT
from trading_os.cli.main import main
from trading_os.devtools import gen
from trading_os.devtools.typescript import Schemas, generate, quote_key, read_side, structure, type_name
from trading_os.domain.risk.lockout import KILL_SWITCH_REASON
from trading_os.shared.events.base import EVENT_REGISTRY, Event


def render(schema: dict[str, Any], **components: Any) -> str:
    return Schemas(components).of(schema)


# ------------------------------------------------------------------------------------------------------ the constructs


def test_scalars_enums_and_constants() -> None:
    assert render({"type": "string"}) == "string"
    assert render({"type": "integer"}) == "number" and render({"type": "number"}) == "number"
    assert render({"type": "boolean"}) == "boolean" and render({"type": "null"}) == "null"
    assert render({"type": "string", "enum": ["buy", "sell"]}) == '"buy" | "sell"'
    assert render({"const": "OBSERVE"}) == '"OBSERVE"'
    assert render({"type": "string", "format": "date-time"}) == "string"  # an instant travels as ISO 8601 text


def test_nullable_and_unions() -> None:
    assert render({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "string | null"
    assert render({"anyOf": [{"type": "string"}, {"type": "string"}]}) == "string"  # no duplicate members
    assert render({"oneOf": [{"type": "integer"}, {"type": "boolean"}]}) == "number | boolean"


def test_arrays_tuples_and_records() -> None:
    assert render({"type": "array", "items": {"type": "string"}}) == "string[]"
    assert render({"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}}) == "(string | null)[]"
    assert render({"type": "array", "prefixItems": [{"type": "number"}, {"type": "string"}]}) == "[number, string]"
    assert render({"type": "object", "additionalProperties": {"type": "number"}}) == "Record<string, number>"
    assert render({"type": "object"}) == "Record<string, unknown>"


def test_objects_mark_optional_what_is_not_required_and_quote_odd_keys() -> None:
    schema = {"type": "object", "properties": {"a": {"type": "string"}, "b-c": {"type": "number"}}, "required": ["a"]}
    assert render(schema) == '{ a: string; "b-c"?: number; }'
    assert quote_key("ok_1") == "ok_1" and quote_key("1st") == '"1st"' and quote_key("a b") == '"a b"'


def test_references_resolve_to_declared_names_and_an_unknown_one_is_an_error() -> None:
    assert render({"$ref": "#/components/schemas/Side"}, Side={"type": "string"}) == "Side"
    assert render({"$ref": "#/components/schemas/Risk-Output"}, **{"Risk-Output": {"type": "object"}}) == "RiskOutput"
    with pytest.raises(KeyError, match="unresolved"):
        render({"$ref": "#/components/schemas/Missing"})


def test_a_declaration_is_an_interface_with_its_documentation() -> None:
    schemas = Schemas({})
    text = schemas.declaration(
        "Thing",
        {
            "type": "object",
            "description": "A thing\nover two lines.",
            "properties": {"id": {"type": "string", "description": "its id"}, "n": {"type": "number"}},
            "required": ["id"],
        },
    )
    assert (
        text
        == "/** A thing over two lines. */\nexport interface Thing {\n  /** its id */\n  id: string;\n  n?: number;\n}"
    )
    assert schemas.declaration("Mode", {"type": "string", "enum": ["a", "b"]}) == 'export type Mode = "a" | "b";'


def test_the_names_of_split_schemas_are_joined() -> None:
    assert type_name("RiskProfile-Output") == "RiskProfileOutput" and type_name("Account") == "Account"


def test_what_does_not_change_a_type_does_not_make_two_schemas_differ() -> None:
    a = {"type": "object", "title": "X", "properties": {"n": {"type": "string", "default": None, "title": "N"}}}
    b = {"type": "object", "properties": {"n": {"type": "string"}}}
    assert structure(a) == structure(b)
    assert structure({"type": "string"}) != structure({"type": "number"})


def test_a_standalone_schema_reads_the_output_variant_of_a_split_model() -> None:
    node = {"properties": {"p": {"$ref": "#/components/schemas/Profile"}, "q": {"$ref": "#/components/schemas/Plain"}}}
    fixed = read_side(node, {"Profile-Input", "Profile-Output", "Plain"})
    assert fixed["properties"]["p"]["$ref"].endswith("Profile-Output") and fixed["properties"]["q"]["$ref"].endswith(
        "Plain"
    )


# ------------------------------------------------------------------------------------------------------ a whole document


DOCUMENT: dict[str, Any] = {
    "paths": {
        "/api/things/{thing_id}": {
            "get": {
                "operationId": "things_get",
                "parameters": [
                    {"name": "thing_id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
                ],
                "responses": {
                    "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}}}
                },
            },
            "delete": {"operationId": "things_delete", "responses": {"204": {"description": "gone"}}},
        },
        "/api/things": {
            "post": {
                "operationId": "things_create",
                "requestBody": {
                    "required": False,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ThingRequest"}}},
                },
                "responses": {
                    "201": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Thing"}}}}
                },
            }
        },
    },
    "components": {
        "schemas": {
            "Thing": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            "ThingRequest": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        }
    },
}


def test_the_operation_table_types_parameters_body_and_response() -> None:
    text = generate(DOCUMENT)
    assert (
        'things_get: {\n    method: "GET";\n    path: "/api/things/{thing_id}";\n    pathParams: { thing_id: string; };'
        in text
    )
    assert "query: { limit?: number; };" in text and "response: Thing;" in text
    assert "things_delete: {" in text and "response: void;" in text
    assert "body: ThingRequest | undefined;" in text  # a body that may be omitted says so
    assert 'things_get: { method: "GET", path: "/api/things/{thing_id}" },' in text


def test_events_become_a_typed_union_without_the_envelope_fields() -> None:
    event = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "occurredAt": {"type": "string"},
            "accountId": {"type": "string"},
            "correlationId": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["id", "reason"],
        "$defs": {},
    }
    text = generate(DOCUMENT, {"autonomy.halted": event})
    assert '"autonomy.halted": { reason: string; };' in text
    assert "export type CockpitEvent" in text and "export type EventType = keyof EventPayloads;" in text


def test_the_strings_the_core_compares_by_are_emitted_as_constants() -> None:
    text = generate(DOCUMENT, None, {"B_REASON": "é", "A_REASON": "Kill switch"})
    assert text.index("A_REASON") < text.index("B_REASON")  # sorted: the output does not depend on the order given
    assert 'export const A_REASON = "Kill switch" as const;' in text and 'export const B_REASON = "é" as const;' in text
    assert "constants" not in generate(DOCUMENT)  # none given, no section


def test_a_limit_the_core_refuses_beyond_is_emitted_as_a_number() -> None:
    text = generate(DOCUMENT, None, {"SOME_LIMIT_DAYS": 31})
    assert "export const SOME_LIMIT_DAYS = 31 as const;" in text  # a number literal, not the string "31"


def test_a_name_given_two_different_schemas_stops_the_generation() -> None:
    event = {
        "type": "object",
        "properties": {},
        "$defs": {"Thing": {"type": "object", "properties": {"id": {"type": "number"}}}},
    }
    with pytest.raises(ValueError, match="two different schemas named 'Thing'"):
        generate(DOCUMENT, {"x.y": event})


# ------------------------------------------------------------------------------------------------------ the real application


@pytest.fixture(scope="module")
def generated() -> str:
    return gen.build()


def test_the_real_document_generates_and_every_reference_resolves(generated: str) -> None:
    assert generated.startswith("/* eslint-disable */")
    assert "export interface Account {" in generated and "export interface Operations {" in generated
    assert "accounts_list: {" in generated and "execution_submit: {" in generated
    for name in ("RiskStatus", "ExecutionOutcome", "StrategyEvaluation", "MarketContextState", "ErrorBody"):
        assert re.search(rf"export (interface|type) {name}\b", generated), name


def test_what_the_server_always_sends_is_not_optional_in_what_a_client_reads(generated: str) -> None:
    account = re.search(r"export interface Account \{(.*?)\n\}", generated, re.DOTALL)
    assert account is not None
    assert "?:" not in account.group(1)  # every field of an account is present when read
    request = re.search(r"export interface CommandRequest \{(.*?)\n\}", generated, re.DOTALL)
    assert request is not None and "stopLoss?:" in request.group(
        1
    )  # …and a client may leave a default out when sending


def test_the_validation_error_is_the_cores_own_envelope_not_the_frameworks(generated: str) -> None:
    assert "HTTPValidationError" not in generated
    body = re.search(r"export interface ErrorBody \{(.*?)\n\}", generated, re.DOTALL)
    assert body is not None and "code: string;" in body.group(1) and "message: string;" in body.group(1)


def test_an_event_registered_by_something_else_in_the_process_is_not_part_of_the_contract() -> None:
    """The event registry is process-wide: a test (or a plugin) that defines its own event must not change the file the cockpit is
    compiled against — a full test run used to write a different contract than a lone one."""

    class Foreign(Event):
        wire_type = "test.foreign_to_the_contract"

    try:
        assert "test.foreign_to_the_contract" in EVENT_REGISTRY  # it is registered…
        assert "test.foreign_to_the_contract" not in gen.event_schemas()  # …and still not generated
        assert "test.foreign_to_the_contract" not in gen.build()
    finally:
        EVENT_REGISTRY.pop("test.foreign_to_the_contract", None)


def test_every_event_and_the_snapshot_have_a_payload_type(generated: str) -> None:
    assert '"system.snapshot": {' in generated and '"risk.state_updated": {' in generated
    assert '"autonomy.halted": {' in generated and '"execution.command_created": {' in generated
    assert "accountStates: Record<string, AccountState>;" in generated


def test_the_cockpit_reads_the_kill_switch_reason_from_the_core_not_from_a_copy(generated: str) -> None:
    assert f'export const KILL_SWITCH_REASON = "{KILL_SWITCH_REASON}" as const;' in generated


def test_the_cockpit_reads_how_far_back_a_strategy_read_may_reach_from_the_core_not_from_a_copy(generated: str) -> None:
    assert f"export const STRATEGY_MAX_LOOKBACK_DAYS = {MAX_LOOKBACK.days} as const;" in generated


def test_no_secret_shaped_field_reaches_a_type_the_browser_reads(generated: str) -> None:
    """A secret travels in one direction: only the request models carry one (and the words in a comment are not fields)."""
    secret_field = re.compile(r'^\s+"?\w*(password|secret|token)\w*"?\??:', re.IGNORECASE | re.MULTILINE)
    carriers = {
        "ConnectRequest",
        "CredentialRequest",
        "DiscoverRequest",
    }  # requests only: browser -> core (ADR 0013, 0020)
    for block in re.finditer(r"export interface (\w+) \{(.*?)\n\}", generated, re.DOTALL):
        name, body = block.group(1), block.group(2)
        if name in carriers:
            continue
        assert not secret_field.search(body), f"{name} has a secret-shaped field"
    for name in carriers:
        assert re.search(rf"export interface {name} \{{.*?password", generated, re.DOTALL)


# ------------------------------------------------------------------------------------------------------ the committed file


def test_the_committed_types_are_the_ones_the_core_would_write_today() -> None:
    """Change a model and forget to generate, and the cockpit would be compiled against a contract the core no longer keeps."""
    committed = REPO_ROOT / "lib" / "api" / "generated.ts"
    if not committed.exists():
        pytest.skip("this checkout has no cockpit (lib/api/generated.ts)")
    assert not gen.is_stale(committed), "run `python -m trading_os gen-types`"
    assert main(["gen-types", "--check", "--out", str(committed)]) == 0


def test_gen_types_writes_and_checks_a_file(tmp_path: Any, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "generated.ts"
    assert main(["gen-types", "--check", "--out", str(target)]) == 1 and "STALE" in capsys.readouterr().out
    assert main(["gen-types", "--out", str(target)]) == 0 and "wrote" in capsys.readouterr().out
    assert target.read_text(encoding="utf-8").startswith("/* eslint-disable */")
    assert main(["gen-types", "--check", "--out", str(target)]) == 0 and "up to date" in capsys.readouterr().out
