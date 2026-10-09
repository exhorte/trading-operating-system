"""The accounts routes' models.

**Secrets travel in one direction.** A model that carries a ``SecretStr`` is a *request* (``…Request``, built on
``SecretRequest``): the password arrives, is used for the call (or handed to the credential store the user chose), and is not a
field of anything that goes back out. ``tests/architecture`` enforces it: a secret-looking field is allowed in a ``…Request``
model of this package, as a ``SecretStr``, and nowhere else.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic.alias_generators import to_camel

from trading_os.domain.accounts.rules_ledger import CancelOutcome
from trading_os.domain.primitives import DomainModel


class SecretRequest(BaseModel):
    """Base of every request that carries a secret: camelCase like the rest, strict about unknown fields."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True)


class ConnectRequest(SecretRequest):
    """Optional: without a password the core attaches to the terminal as it is (already logged in), or reads the vault the
    user opted into (ADR 0013). A password given here is used for this call only."""

    password: SecretStr | None = None


class CredentialRequest(SecretRequest):
    """Write-only: the vault never gives a password back."""

    password: SecretStr = Field(min_length=1)


class AccountUpdate(DomainModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    terminal_path: str | None = None
    symbol_suffix: str | None = Field(default=None, max_length=10)


class TradingSwitch(DomainModel):
    enabled: bool


class ActiveAccountRequest(DomainModel):
    account_id: str


class ActiveAccountView(DomainModel):
    account_id: str | None


class CredentialStatus(DomainModel):
    store: str  # none | windows | env
    stored: bool  # whether one exists — the value is never readable


class CancelResult(DomainModel):
    outcome: CancelOutcome
