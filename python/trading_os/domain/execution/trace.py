"""The short trace an order carries in its broker comment — computed exactly as the execution agent computes it.

A broker keeps about 31 characters of comment, and a command id is up to 64: the agent writes ``"TOS "`` followed by the
first 16 hex characters of SHA-256(commandId) (20 characters in all; ``CommandTrace`` in
``tools/mt5-execution-agent/Include/CommandStore.mqh``). The core recomputes the same value to tie a position, a pending
order or a deal found at the broker back to the command that produced it — without the agent having to be connected.

The two implementations are a contract: the vector in ``tests/unit/domain/test_trace_and_resolution.py`` pins this one,
and any change to the agent's algorithm must change both.
"""

from __future__ import annotations

import hashlib

TRACE_PREFIX = "TOS "
_HEX_CHARS = 16


def command_trace(command_id: str) -> str:
    return TRACE_PREFIX + hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:_HEX_CHARS]


def is_trace(comment: str) -> bool:
    """A comment shaped like one of ours (it says nothing about *which* command)."""
    return comment.startswith(TRACE_PREFIX) and len(comment) == len(TRACE_PREFIX) + _HEX_CHARS
