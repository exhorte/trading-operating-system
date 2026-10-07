"""Shared fixtures. Tests never read the developer's real ``.env`` and never touch the real database."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from trading_os.shared.logging.redaction import clear_secrets


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in list(os.environ):
        if name.startswith(("TRADINGOS_", "MT5_PASSWORD_")) or name in {
            "DATABASE_URL",
            "FRED_API_KEY",
            "TRADING_MODE",
            "ACTIVE_ACCOUNT_ID",
            "CREDENTIAL_STORE",
            "MT5_ENABLED",
        }:
            monkeypatch.delenv(name, raising=False)
    clear_secrets()
    yield
    clear_secrets()
