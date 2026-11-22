"""Is the agent of a terminal technically ready? (ADR 0039 § 5 and § 9, I7) — one pure function, one reading, no decision.

``READY`` is a reading of fourteen conditions, never a stored value: any red makes it ``BLOCKED`` (the situation forbids), any pending one makes it ``VALIDATING``
(not yet known), all green makes it ``READY``. It is **technical**: whether an order may be placed is another line, ``Execution Authorization``, with its own
reasons. Product identity follows C6 (option b): a product deduced from the symbol suffix is green only if Exhorte declared the same one, and never "confirmed".
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from trading_os.shared.ea_readiness import (
    HEARTBEAT_FRESH_S,
    HEARTBEAT_STALE_S,
    EaReadiness,
    Light,
    ReadinessInput,
    evaluate_ea_readiness,
)

CAPS = ("ping", "halt", "dead_man", "limit", "modify", "close", "cancel")


def good(**changes: object) -> ReadinessInput:
    base = ReadinessInput(
        terminal_running=True,
        hello_received=True,
        declared_login="486046157",
        declared_provider="EXNESS",
        declared_product="EXNESS_STANDARD",
        declared_symbols=("XAUUSDm", "EURUSDm"),
        declared_chart_symbol="XAUUSDm",
        agent_version="1.13",
        capabilities=CAPS,
        protocol_version=None,
        agent_login="486046157",
        identity="ok",
        heartbeat_age_s=3.0,
        core_silent_ms=1200,
        attached_experts=(),
        core_ok=True,
        mt5_connected=True,
        broker_product="EXNESS_STANDARD",
        product_observed=True,
        identification_blockers=(),
        identification_executable=True,
        readiness_checks={"no_critical_incident": True, "account_limits_configured": True},
        attach_reconciled=True,
        unresolved_commands=0,
        reported_params_match=None,
        reported_chart=None,
        execution_mode="OFF",
        agent_compiled_mode="OBSERVE",
        halted=False,
        tradable=False,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def lights(result: EaReadiness) -> dict[str, Light]:
    return {condition.code: condition.light for condition in result.conditions}


# ------------------------------------------------------------------------------------------------ the verdict


def test_everything_green_with_the_declared_product_is_ready_with_the_honest_warnings() -> None:
    result = evaluate_ea_readiness(good())
    assert result.verdict == "READY" and result.red_codes == () and result.pending_codes == ()
    assert "PRODUCT_UNCONFIRMED" in result.warning_codes, "a product deduced from a suffix is never shown as confirmed"
    assert {"PROTOCOL_VERSION_UNREPORTED", "CHART_UNVERIFIED", "PARAMETERS_UNREPORTED"} <= set(result.warning_codes)
    assert result.header_code is None


def test_ready_is_technical_the_authorization_to_execute_is_a_separate_line_with_its_reasons() -> None:
    result = evaluate_ea_readiness(good())
    assert result.verdict == "READY"
    authorization = result.execution_authorization
    assert authorization.allowed is False
    assert {"SYSTEM_MODE_OFF", "AGENT_COMPILED_OBSERVE", "ACCOUNT_NOT_TRADABLE"} <= set(authorization.reasons)


def test_a_halted_agent_is_still_ready_and_says_it_is_halted() -> None:
    result = evaluate_ea_readiness(good(halted=True))
    assert result.verdict == "READY" and "HALTED" in result.execution_authorization.reasons


def test_the_machine_never_says_more_than_ready() -> None:
    result = evaluate_ea_readiness(good(execution_mode="AUTONOMOUS", tradable=True, agent_compiled_mode="CONFIRM"))
    assert result.verdict == "READY", "the verdict is about the agent's attachment, whatever the mode"


def test_no_hello_is_not_a_verdict_but_a_pending_condition() -> None:
    result = evaluate_ea_readiness(good(hello_received=False))
    assert result.verdict == "VALIDATING" and "NO_HELLO" in result.pending_codes


# ------------------------------------------------------------------------------------------------ C6: the identity of the product


def test_a_product_deduced_from_a_suffix_with_no_declaration_is_red_and_the_header_says_the_identity_is_unverified() -> (
    None
):
    result = evaluate_ea_readiness(good(declared_product=None))
    assert result.verdict == "BLOCKED" and "PRODUCT_UNDECLARED" in result.red_codes
    assert result.header_code == "ACCOUNT_IDENTITY_UNVERIFIED"


def test_a_different_declaration_is_red() -> None:
    result = evaluate_ea_readiness(good(declared_product="FTMO_CHALLENGE_2STEP"))
    assert "PRODUCT_MISMATCH" in result.red_codes and result.header_code == "ACCOUNT_IDENTITY_UNVERIFIED"


def test_the_same_declaration_is_green_with_a_warning_never_confirmed() -> None:
    result = evaluate_ea_readiness(good())
    assert lights(result)["PRODUCT_IDENTITY"] is Light.GREEN
    assert "PRODUCT_UNCONFIRMED" in result.warning_codes and "PRODUCT_CONFIRMED" not in result.warning_codes


def test_a_contract_declared_to_the_core_stands_for_a_declaration_of_the_product() -> None:
    """ADR 0039 § 9: for an FTMO account the contract the user declared (ADR 0036) is the declaration — no second one is asked."""
    result = evaluate_ea_readiness(
        good(declared_product=None, product_observed=False, broker_product="FTMO_CHALLENGE_2STEP")
    )
    assert lights(result)["PRODUCT_IDENTITY"] is Light.GREEN and "PRODUCT_UNCONFIRMED" not in result.warning_codes


@pytest.mark.parametrize(
    "blocker",
    [
        "account_facts_missing",
        "provider_not_identified",
        "provider_ambiguous",
        "provider_mismatch",
        "environment_mismatch",
        "account_product_unknown",
    ],
)
def test_every_identity_blocker_of_the_core_is_red_with_its_own_code(blocker: str) -> None:
    result = evaluate_ea_readiness(good(identification_blockers=(blocker,), identification_executable=False))
    assert result.verdict == "BLOCKED" and blocker in result.red_codes
    assert result.header_code == "ACCOUNT_IDENTITY_UNVERIFIED"


def test_an_unknown_broker_product_is_red() -> None:
    result = evaluate_ea_readiness(good(broker_product=None))
    assert result.verdict == "BLOCKED" and result.header_code == "ACCOUNT_IDENTITY_UNVERIFIED"


# ------------------------------------------------------------------------------------------------ the other conditions


def test_the_wrong_login_is_red_whatever_the_agent_says_of_itself() -> None:
    result = evaluate_ea_readiness(good(agent_login="123"))
    assert "MT5_ACCOUNT_MISMATCH" in result.red_codes
    assert "MT5_ACCOUNT_MISMATCH" in evaluate_ea_readiness(good(identity="mismatch")).red_codes


def test_an_incompatible_agent_is_red_and_nothing_continues() -> None:
    result = evaluate_ea_readiness(good(agent_version="", protocol_version=None))
    assert result.verdict == "BLOCKED" and "EA_PROTOCOL_INCOMPATIBLE" in result.red_codes


def test_a_symbol_outside_the_declared_list_is_red() -> None:
    result = evaluate_ea_readiness(good(declared_chart_symbol="GBPUSDm"))
    assert "SYMBOL_NOT_ALLOWED" in result.red_codes


def test_a_chart_the_agent_reports_that_is_not_the_declared_one_is_red_and_a_matching_one_clears_the_warning() -> None:
    assert "CHART_MISMATCH" in evaluate_ea_readiness(good(reported_chart=("EURUSDm", "M5"))).red_codes
    matching = evaluate_ea_readiness(good(reported_chart=("XAUUSDm", "M5")))
    assert "CHART_UNVERIFIED" not in matching.warning_codes and "CHART_MISMATCH" not in matching.red_codes


def test_parameters_that_do_not_match_the_preset_are_red_and_unreported_ones_are_a_warning() -> None:
    assert "PARAMETERS_MISMATCH" in evaluate_ea_readiness(good(reported_params_match=False)).red_codes
    assert "PARAMETERS_UNREPORTED" not in evaluate_ea_readiness(good(reported_params_match=True)).warning_codes


@pytest.mark.parametrize(
    ("age", "light"),
    [
        (None, Light.PENDING),
        (0.0, Light.GREEN),
        (HEARTBEAT_FRESH_S - 0.1, Light.GREEN),
        (HEARTBEAT_FRESH_S, Light.PENDING),
        (HEARTBEAT_STALE_S - 0.1, Light.PENDING),
        (HEARTBEAT_STALE_S, Light.RED),
    ],
)
def test_the_heartbeat_has_three_thresholds_and_says_which_one_was_crossed(age: float | None, light: Light) -> None:
    assert lights(evaluate_ea_readiness(good(heartbeat_age_s=age)))["HEARTBEAT_FRESH"] is light


def test_a_broker_that_is_not_connected_is_red() -> None:
    assert "BROKER_NOT_CONNECTED" in evaluate_ea_readiness(good(mt5_connected=False)).red_codes


def test_a_core_that_is_not_ok_is_red() -> None:
    assert "CORE_NOT_OK" in evaluate_ea_readiness(good(core_ok=False)).red_codes


def test_a_critical_incident_or_unwritten_limits_are_red_with_their_own_codes() -> None:
    result = evaluate_ea_readiness(
        good(readiness_checks={"no_critical_incident": False, "account_limits_configured": False})
    )
    assert {"CRITICAL_INCIDENT", "ACCOUNT_LIMITS_NOT_CONFIGURED"} <= set(result.red_codes)


def test_an_agent_without_the_dead_man_capability_is_not_ready_but_the_core_is_not_told_to_refuse_it() -> None:
    result = evaluate_ea_readiness(good(capabilities=("ping", "halt")))
    assert "LOCAL_PROTECTIONS_MISSING" in result.red_codes


def test_protections_are_announced_and_received_never_proven() -> None:
    result = evaluate_ea_readiness(good())
    assert "LOCAL_PROTECTIONS_ANNOUNCED_ONLY" in result.warning_codes
    assert "PING_NOT_YET_RECEIVED" in evaluate_ea_readiness(good(core_silent_ms=None)).pending_codes


def test_a_third_party_expert_in_the_terminal_blocks_the_preparation() -> None:
    result = evaluate_ea_readiness(good(attached_experts=("Ultimate_ICT_Gold_Scalper_v4.0",)))
    assert "THIRD_PARTY_EA_ATTACHED" in result.red_codes


def test_reconciliation_not_done_since_the_attachment_keeps_the_terminal_validating() -> None:
    result = evaluate_ea_readiness(good(attach_reconciled=False))
    assert result.verdict == "VALIDATING" and "RECONCILIATION_PENDING" in result.pending_codes
    assert evaluate_ea_readiness(good(attach_reconciled=None)).verdict == "VALIDATING"


def test_a_command_in_doubt_blocks_even_when_the_reconciliation_ran() -> None:
    result = evaluate_ea_readiness(good(unresolved_commands=1))
    assert result.verdict == "BLOCKED" and "UNRESOLVED_COMMANDS" in result.red_codes


def test_a_red_wins_over_a_pending() -> None:
    result = evaluate_ea_readiness(good(attach_reconciled=False, mt5_connected=False))
    assert result.verdict == "BLOCKED"


def test_unknown_facts_are_pending_never_green() -> None:
    result = evaluate_ea_readiness(
        good(
            core_ok=None, mt5_connected=None, readiness_checks={}, identification_executable=None, attached_experts=None
        )
    )
    assert result.verdict == "VALIDATING"
    assert {"CORE_NOT_OK_UNKNOWN", "BROKER_CONNECTION_UNKNOWN"} & set(result.pending_codes)


def test_every_condition_has_a_label_and_a_detail() -> None:
    result = evaluate_ea_readiness(good())
    assert len(result.conditions) == 14
    assert all(condition.label and condition.detail for condition in result.conditions)
