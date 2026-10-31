"""Number behaviour that must match JavaScript's, because it is the behaviour the ported TypeScript detectors were written (and their
golden vectors generated) against.

Three places where Python's defaults differ and a detector would silently drift:

* ``Math.round`` rounds ties toward +∞ (``round(2.5) == 3``, ``round(-2.5) == -2``); Python's ``round`` rounds ties to even;
* ``Number.prototype.toFixed`` rounds the *exact* binary value half up; ``format(x, ".3f")`` rounds half to even;
* a whole number prints without a decimal point (``String(3) == "3"``), a Python float prints ``3.0``.

``sum()`` is deliberately absent: from Python 3.12 it compensates float additions, JavaScript's ``reduce`` does not. A port that needs a
total adds in a loop.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal


def js_round(value: float) -> float:
    """``Math.round``: the nearest integer, ties toward +∞."""
    if not math.isfinite(value):
        return value
    floor = math.floor(value)
    return float(floor + 1) if value - floor >= 0.5 else float(floor)


def to_fixed(value: float, digits: int) -> str:
    """``Number.prototype.toFixed``: the exact binary value rounded half up to ``digits`` decimals."""
    if value != value:
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if abs(value) >= 1e21:
        return number_to_string(value)
    if value == 0:
        value = 0.0  # (-0).toFixed(2) is "0.00"
    quantum = Decimal(1).scaleb(-digits)
    return format(Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP), "f")


def number_to_string(value: float) -> str:
    """``String(value)`` for a JavaScript number: shortest round-trip digits, no ``.0`` on whole numbers, exponent form only
    outside [1e-6, 1e21)."""
    if value != value:
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    sign_free = Decimal(repr(abs(value)))
    _, digit_tuple, exponent = sign_free.as_tuple()
    digits = "".join(map(str, digit_tuple)).rstrip("0") or "0"
    if isinstance(exponent, str):  # pragma: no cover - cannot happen for a finite number
        raise ValueError(value)
    # the position of the decimal point relative to the digit string: value = 0.<digits> * 10**point
    point = len("".join(map(str, digit_tuple))) + exponent
    count = len(digits)
    if count <= point <= 21:
        return sign + digits + "0" * (point - count)
    if 0 < point <= 21:
        return sign + digits[:point] + "." + digits[point:]
    if -6 < point <= 0:
        return sign + "0." + "0" * (-point) + digits
    exp = point - 1
    mantissa = digits[0] + ("." + digits[1:] if count > 1 else "")
    return f"{sign}{mantissa}e{'+' if exp >= 0 else '-'}{abs(exp)}"
