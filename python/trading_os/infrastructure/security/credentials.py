"""``CredentialStore``: where a broker password may live, if the user chooses to let it live anywhere (ADR 0013).

* ``none`` (the default) — nothing is stored. A password given to ``connect`` is used for that call and forgotten; the
  terminal itself remembers the login. This is the only mode that needs no trust in the machine.
* ``windows`` — the operating system's credential vault (Windows Credential Manager, through ``keyring``), opt-in. The
  secret is **write-only** from the outside: the API can set or delete one, never read it back — only ``AccountService``
  reads it, to log a terminal in.
* ``env`` — ``MT5_PASSWORD_<ACCOUNT_ID>`` in the process environment. Development only; read-only.

A password is a ``SecretStr`` from the moment it arrives, is registered with the log masker while it exists, and is never
a field of any model, event, table or response.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Protocol

from pydantic import SecretStr

from trading_os.shared.errors import Forbidden

SERVICE_NAME = "trading-os-mt5"


class CredentialStore(Protocol):
    name: str

    async def get(self, account_id: str) -> SecretStr | None: ...
    async def put(self, account_id: str, password: SecretStr) -> None: ...
    async def delete(self, account_id: str) -> None: ...
    async def has(self, account_id: str) -> bool: ...


class NullCredentialStore:
    name = "none"

    async def get(self, account_id: str) -> SecretStr | None:
        return None

    async def put(self, account_id: str, password: SecretStr) -> None:
        raise Forbidden(
            "credential storage is disabled (CREDENTIAL_STORE=none): the password is used once and not kept",
            code="credential_store_disabled",
        )

    async def delete(self, account_id: str) -> None:
        return None

    async def has(self, account_id: str) -> bool:
        return False


class EnvCredentialStore:
    """Development convenience: ``MT5_PASSWORD_<ACCOUNT_ID>`` (id upper-cased, non-alphanumerics → ``_``)."""

    name = "env"

    @staticmethod
    def variable(account_id: str) -> str:
        return "MT5_PASSWORD_" + re.sub(r"[^A-Za-z0-9]", "_", account_id).upper()

    async def get(self, account_id: str) -> SecretStr | None:
        value = os.environ.get(self.variable(account_id))
        return SecretStr(value) if value else None

    async def put(self, account_id: str, password: SecretStr) -> None:
        raise Forbidden(
            "the environment store is read-only: set the variable yourself", code="credential_store_readonly"
        )

    async def delete(self, account_id: str) -> None:
        raise Forbidden(
            "the environment store is read-only: unset the variable yourself", code="credential_store_readonly"
        )

    async def has(self, account_id: str) -> bool:
        return bool(os.environ.get(self.variable(account_id)))


class KeyringCredentialStore:
    """The OS vault. ``keyring`` calls are blocking: they run in a thread."""

    name = "windows"

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self._service = service

    async def get(self, account_id: str) -> SecretStr | None:
        import keyring

        value = await asyncio.to_thread(keyring.get_password, self._service, account_id)
        return SecretStr(value) if value else None

    async def put(self, account_id: str, password: SecretStr) -> None:
        import keyring

        await asyncio.to_thread(keyring.set_password, self._service, account_id, password.get_secret_value())

    async def delete(self, account_id: str) -> None:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            await asyncio.to_thread(keyring.delete_password, self._service, account_id)
        except PasswordDeleteError:
            return None  # nothing was stored: the postcondition holds

    async def has(self, account_id: str) -> bool:
        return await self.get(account_id) is not None


def build_credential_store(kind: str) -> CredentialStore:
    if kind == "windows":
        return KeyringCredentialStore()
    if kind == "env":
        return EnvCredentialStore()
    return NullCredentialStore()
