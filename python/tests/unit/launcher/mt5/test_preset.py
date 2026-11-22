"""The preset (``.set``) and the start-up file of a terminal (ADR 0039 §§ 4 and 5, I5): pure functions first. The preset says only what Exhorte declared and
what the agent's own source allows; it never names a token, a password, or the lists of logins an order may reach."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit.launcher.mt5.support import declared
from trading_os.launcher.mt5.model import ChartSpec, DeclaredTerminal
from trading_os.launcher.mt5.preset import PresetRefused, build_preset, parse_inputs, render_set
from trading_os.launcher.mt5.startup_ini import ALLOWED_KEYS, render_startup_ini

REAL_SOURCE = Path(__file__).resolve().parents[5] / "tools" / "mt5-execution-agent" / "TradingOsAgent.mq5"
INPUTS = parse_inputs(REAL_SOURCE.read_text(encoding="utf-8"))
NAMES = {item.name for item in INPUTS}


# ------------------------------------------------------------------------------------------------ the inputs of the agent


def test_the_inputs_are_read_from_the_agents_own_source() -> None:
    assert {"InpCoreHost", "InpCorePort", "InpAccountId", "InpMagicNumber", "InpAllowedSymbolsCsv"} <= NAMES
    by_name = {item.name: item for item in INPUTS}
    assert by_name["InpCorePort"].default == "9765" and by_name["InpCorePort"].type == "int"
    assert by_name["InpCoreHost"].default == "127.0.0.1" and by_name["InpCoreHost"].type == "string"
    assert by_name["InpMaxVolumePerOrder"].type == "double"


def test_a_trailing_comment_is_not_part_of_a_default() -> None:
    (item,) = parse_inputs('input int InpX = 5; // five, not "5; // five"\n')
    assert item.default == "5"


# ------------------------------------------------------------------------------------------------ the preset


def test_the_preset_carries_what_was_declared_and_nothing_invented() -> None:
    preset = build_preset(declared(), INPUTS, core_port=9765)
    values = dict(preset.values)
    assert values["InpAccountId"] == "486046157"
    assert values["InpMagicNumber"] == "486046"
    assert values["InpAllowedSymbolsCsv"] == "XAUUSDm,EURUSDm"
    assert values["InpCoreHost"] == "127.0.0.1" and values["InpCorePort"] == "9765"
    assert set(values) <= NAMES, "a preset names only inputs that the source declares"


def test_the_lists_of_logins_an_order_may_reach_are_always_empty() -> None:
    values = dict(build_preset(declared(), INPUTS, core_port=9765).values)
    lists = [name for name in values if name.endswith("Logins")]
    assert lists, "the source has such inputs"
    assert all(values[name] == "" for name in lists)


def test_an_input_the_launcher_does_not_decide_keeps_the_default_of_the_source() -> None:
    values = dict(build_preset(declared(), INPUTS, core_port=9765).values)
    defaults = {item.name: item.default for item in INPUTS}
    assert values["InpHeartbeatSeconds"] == defaults["InpHeartbeatSeconds"]
    assert values["InpMaxVolumePerOrder"] == defaults["InpMaxVolumePerOrder"]


def test_no_key_or_value_of_a_preset_can_be_a_secret() -> None:
    secret = re.compile(r"token|password|passwd|secret|credential|api_?key", re.IGNORECASE)
    values = build_preset(declared(), INPUTS, core_port=9765).values
    assert not [name for name, value in values if secret.search(name) or secret.search(value)]


@pytest.mark.parametrize("missing", ["expected_login", "magic", "allowed_symbols", "chart"])
def test_a_declaration_that_is_incomplete_makes_no_preset_and_names_what_is_missing(missing: str) -> None:
    empty = {"expected_login": None, "magic": None, "allowed_symbols": (), "chart": None}[missing]
    with pytest.raises(PresetRefused) as refused:
        build_preset(declared(**{missing: empty}), INPUTS, core_port=9765)
    assert any(word in " ".join(refused.value.problems) for word in ("login", "magique", "symboles", "graphique"))


def test_a_declaration_with_nothing_in_it_is_refused_with_every_missing_item() -> None:
    with pytest.raises(PresetRefused) as refused:
        build_preset(DeclaredTerminal(), INPUTS, core_port=9765)
    assert len(refused.value.problems) >= 4


def test_an_agent_without_the_input_that_binds_it_to_a_login_cannot_be_prepared() -> None:
    without = [item for item in INPUTS if item.name != "InpAccountId"]
    with pytest.raises(PresetRefused) as refused:
        build_preset(declared(), without, core_port=9765)
    assert any("InpAccountId" in problem for problem in refused.value.problems)


def test_the_preset_is_written_the_way_metatrader_writes_its_own() -> None:
    """UTF-16 little-endian with a byte-order mark and CRLF line ends: the format of the preset Exhorte saved from MetaTrader (``ea1.set``)."""
    data = render_set(build_preset(declared(), INPUTS, core_port=9765))
    assert data.startswith(b"\xff\xfe")
    text = data.decode("utf-16")
    assert "\r\n" in text and "\n" not in text.replace("\r\n", "")
    assert "InpMagicNumber=486046\r\n" in text
    assert render_set(build_preset(declared(), INPUTS, core_port=9765)) == data, "deterministic: same input, same bytes"


# ------------------------------------------------------------------------------------------------ the start-up file


def test_the_startup_file_has_one_section_and_four_keys() -> None:
    text = render_startup_ini(
        r"TradingOS\TradingOsAgent", "TradingOS-D0E8.set", ChartSpec(symbol="XAUUSDm", period="M5")
    )
    assert text.splitlines()[0] == "[StartUp]"
    keys = {line.split("=", 1)[0] for line in text.splitlines()[1:] if line.strip()}
    assert keys == set(ALLOWED_KEYS) == {"Expert", "ExpertParameters", "Symbol", "Period"}
    assert "Expert=TradingOS\\TradingOsAgent" in text and "ExpertParameters=TradingOS-D0E8.set" in text
    assert "Symbol=XAUUSDm" in text and "Period=M5" in text
    assert text.count("[") == 1, "no other section"


def test_the_startup_file_holds_no_account_server_permission_or_shutdown() -> None:
    text = render_startup_ini(r"TradingOS\TradingOsAgent", "x.set", ChartSpec(symbol="XAUUSDm", period="M5")).lower()
    for forbidden in ("login", "password", "server", "proxy", "enabled", "allow", "shutdown", "template", "script"):
        assert forbidden not in text, forbidden


@pytest.mark.parametrize(
    ("expert", "preset", "chart"),
    [
        ("Evil\nPassword=x", "a.set", ChartSpec(symbol="XAUUSDm", period="M5")),
        (r"TradingOS\TradingOsAgent", "a.set\n[Common]", ChartSpec(symbol="XAUUSDm", period="M5")),
        (r"TradingOS\TradingOsAgent", "a.set", ChartSpec(symbol="XAU\nLogin=1", period="M5")),
        (r"TradingOS\TradingOsAgent", "a.set", ChartSpec(symbol="XAUUSDm", period="M5\r\n[Experts]")),
    ],
)
def test_a_value_that_could_open_another_line_or_section_is_refused(expert: str, preset: str, chart: ChartSpec) -> None:
    with pytest.raises(ValueError):
        render_startup_ini(expert, preset, chart)
