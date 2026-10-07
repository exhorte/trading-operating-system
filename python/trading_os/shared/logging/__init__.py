"""Logging with secret masking (ADR 0013, I0): nothing written to a log may carry a token or a password."""

from trading_os.shared.logging.redaction import (
    RedactingFormatter,
    clear_secrets,
    redact,
    register_secret,
    unregister_secret,
)
from trading_os.shared.logging.setup import setup_logging

__all__ = ["RedactingFormatter", "clear_secrets", "redact", "register_secret", "setup_logging", "unregister_secret"]
