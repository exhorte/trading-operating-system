"""The start-up file of a terminal (ADR 0039 § 5, I5): what ``terminal64.exe /config:`` is given so that it opens a chart and puts the agent on it.

One section and four keys, and nothing else. It carries no account, no server, no permission, no proxy, no shutdown: the sections that MetaTrader
guards (its permissions, its account) are not written by the launcher, and a value that could open another line or another section is refused.
"""

from __future__ import annotations

import re

from trading_os.launcher.mt5.model import ChartSpec

ALLOWED_KEYS = ("Expert", "ExpertParameters", "Symbol", "Period")
SECTION = "[StartUp]"
_VALUE = re.compile(r"^[A-Za-z0-9._#@$+\\-]{1,128}$")


def render_startup_ini(expert: str, preset_name: str, chart: ChartSpec) -> str:
    values = {"Expert": expert, "ExpertParameters": preset_name, "Symbol": chart.symbol, "Period": chart.period}
    for key, value in values.items():
        if not _VALUE.match(value):
            raise ValueError(
                f"valeur refusée pour {key} : lettres, chiffres et . _ - # @ $ + \\ seulement, sans saut de ligne"
            )
    return SECTION + "\r\n" + "".join(f"{key}={values[key]}\r\n" for key in ALLOWED_KEYS)
