"""The base of every request body that is not a secret carrier (those are ``SecretRequest`` in ``schemas/accounts.py``)."""

from __future__ import annotations

from pydantic import ConfigDict

from trading_os.domain.primitives import DomainModel


class StrictRequest(DomainModel):
    """A request body: an unknown field is an error, not noise — a misspelt ``stopLoss`` must never become « no stop »."""

    model_config = ConfigDict(extra="forbid")
