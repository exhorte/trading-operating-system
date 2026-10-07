"""Classification of MT5 trade return codes (``TRADE_RETCODE_*``).

Three classes, and the middle one is the point (audit F03): a *timeout*, a *processing error* or a *lost connection*
does NOT mean the order was refused — it may be live. Recording it as FAILED would let the system believe nothing is
open while a position exists, and a retry would double the exposure. Those stay UNKNOWN and go to reconciliation.
"""

from __future__ import annotations

from enum import StrEnum

# https://www.mql5.com/en/docs/constants/structures/mqltraderesult — only the ones with a decision attached.
SUCCESS_CODES = frozenset({10008, 10009, 10010})  # PLACED, DONE, DONE_PARTIAL
AMBIGUOUS_CODES = frozenset({10011, 10012, 10031})  # ERROR (processing), TIMEOUT, CONNECTION

_NAMES = {
    "TRADE_RETCODE_PLACED": 10008,
    "TRADE_RETCODE_DONE": 10009,
    "TRADE_RETCODE_DONE_PARTIAL": 10010,
    "TRADE_RETCODE_ERROR": 10011,
    "TRADE_RETCODE_TIMEOUT": 10012,
    "TRADE_RETCODE_CONNECTION": 10031,
}


class RetcodeClass(StrEnum):
    SUCCESS = "success"
    AMBIGUOUS = "ambiguous"  # the order may exist: UNKNOWN + reconciliation, never FAILED, never replayed
    FAILURE = "failure"  # a definite refusal: nothing is open


def parse_retcode(value: str | int | None) -> int | None:
    """The agent sends the code as a string (« 10009 ») or a symbolic name; ``None`` when absent/unreadable."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = value.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return _NAMES.get(text.upper())


def classify_retcode(value: str | int | None) -> RetcodeClass:
    """No code at all is ambiguous too: if we cannot tell, we do not assume the order was refused."""
    code = parse_retcode(value)
    if code is None or code in AMBIGUOUS_CODES:
        return RetcodeClass.AMBIGUOUS
    if code in SUCCESS_CODES:
        return RetcodeClass.SUCCESS
    return RetcodeClass.FAILURE


# The agent marks a refusal that happened *before* any broker call with this phrase (STORE_UNWRITABLE: the journal
# line could not be written, so the order was deliberately not sent). No retcode exists for it, yet it is definite.
NOT_SENT_MARKER = "order NOT sent"


def classify_failed_report(retcode: str | int | None, detail: str) -> RetcodeClass:
    """Classify an agent report whose status is FAILED."""
    if parse_retcode(retcode) is None and NOT_SENT_MARKER in detail:
        return RetcodeClass.FAILURE
    return classify_retcode(retcode)
