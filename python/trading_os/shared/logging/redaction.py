"""Masking of secrets in any text that may reach a log, an API error body or an exception message.

Two layers:
* **registered values** — every secret the process holds (tokens, a password for the time of a login)
  is registered; any occurrence is replaced verbatim, wherever it appears;
* **shapes** — ``Bearer xxx``, ``access_token=xxx``, ``password: xxx`` … are masked even when the value
  was never registered (a token printed by a library, a URL query).
"""

from __future__ import annotations

import logging
import re
import threading

MASK = "***"
_MIN_SECRET_LENGTH = 4  # a 1–3 character "secret" would mask ordinary text; real secrets are longer

_lock = threading.Lock()
_secrets: set[str] = set()

_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")
_KEY_VALUE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|token|authorization)"
    r"(\s*[=:]\s*|\"\s*:\s*\")(?!bearer\s)([^\s&\"',;]+)"  # a "Bearer xxx" value is the previous rule's job
)


def register_secret(value: str | None) -> None:
    """Remember a secret so that every later occurrence is masked. ``None``/too short values are ignored."""
    if value and len(value) >= _MIN_SECRET_LENGTH:
        with _lock:
            _secrets.add(value)


def unregister_secret(value: str | None) -> None:
    """Forget a *transient* secret (a password that lived for the time of one login). Never needed for tokens."""
    if value:
        with _lock:
            _secrets.discard(value)


def clear_secrets() -> None:
    with _lock:
        _secrets.clear()


def redact(text: str) -> str:
    if not text:
        return text
    with _lock:
        known = sorted(_secrets, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, MASK)
    text = _BEARER.sub(lambda m: f"{m.group(1)} {MASK}", text)
    return _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)


class RedactingFormatter(logging.Formatter):
    """Formats the record, then masks the result — so arguments, tracebacks and extra text are all covered."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
