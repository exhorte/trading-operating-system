"""Accounts: the registry, the connection, the single active account, the trading switch, the versioned rules, the vault.

A connection is *runtime*, an account is *configuration*; connecting needs no password when the terminal is already logged in
(ADR 0013), and a password that is given is used once and forgotten. Switching or disconnecting is refused — with the
reasons — while it could hide risk: open positions, pending orders, a command in doubt.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from trading_os.api.schemas.accounts import (
    AccountUpdate,
    ActiveAccountRequest,
    ActiveAccountView,
    CancelResult,
    ConnectRequest,
    CredentialRequest,
    CredentialStatus,
    TradingSwitch,
)
from trading_os.app.dependencies import Core
from trading_os.domain.accounts.models import Account, AccountRules, AccountSnapshot
from trading_os.domain.accounts.rules_ledger import RuleVersion
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.services.accounts import AccountCreate, RulesOverview
from trading_os.shared.errors import NotFound

router = APIRouter(prefix="/api/accounts", tags=["accounts"])
active_router = APIRouter(prefix="/api/active-account", tags=["accounts"])


# ------------------------------------------------------------------------------------------------------ the registry


@router.get("", response_model=list[Account], summary="Every account, with its connection status")
async def list_accounts(c: Core) -> list[Account]:
    return await c.accounts.accounts()


@router.post("", response_model=Account, status_code=201, summary="Register an account (no secret is stored)")
async def create_account(body: AccountCreate, c: Core) -> Account:
    return await c.accounts.create(body)


@router.get("/{account_id}", response_model=Account)
async def get_account(account_id: str, c: Core) -> Account:
    return await c.accounts.get(account_id)


@router.patch("/{account_id}", response_model=Account, summary="Rename, or change the terminal path / symbol suffix")
async def update_account(account_id: str, body: AccountUpdate, c: Core) -> Account:
    return await c.accounts.update(
        account_id, name=body.name, terminal_path=body.terminal_path, symbol_suffix=body.symbol_suffix
    )


@router.delete("/{account_id}", status_code=204, summary="Archive an account (it must be disconnected)")
async def archive_account(account_id: str, c: Core) -> Response:
    await c.accounts.archive(account_id)
    return Response(status_code=204)


@router.put("/{account_id}/trading", response_model=Account, summary="The « Enable / Disable Trading » switch")
async def set_trading(account_id: str, body: TradingSwitch, c: Core) -> Account:
    return await c.accounts.set_trading_enabled(account_id, body.enabled)


# ------------------------------------------------------------------------------------------------------ the connection


@router.post("/{account_id}/connect", response_model=Account, summary="Attach the account's terminal")
async def connect(account_id: str, c: Core, body: ConnectRequest | None = None) -> Account:
    return await c.accounts.connect(account_id, body.password if body else None)


@router.post(
    "/{account_id}/disconnect", response_model=Account, summary="Detach the terminal (refused while risk is open)"
)
async def disconnect(account_id: str, c: Core, force: Annotated[bool, Query()] = False) -> Account:
    return await c.accounts.disconnect(account_id, force=force)


@router.post("/{account_id}/reconnect", response_model=Account, summary="Detach and attach again")
async def reconnect(account_id: str, c: Core) -> Account:
    return await c.accounts.reconnect(account_id)


# ------------------------------------------------------------------------------------------------------ what it holds


@router.get(
    "/{account_id}/snapshot", response_model=AccountSnapshot, summary="Balance, equity, margin — as MT5 shows them"
)
async def snapshot(account_id: str, c: Core) -> AccountSnapshot:
    await c.accounts.get(account_id)
    found = c.positions.snapshot(account_id)
    if found is None:
        raise NotFound("no account snapshot yet: the account is not connected or has not been read", code="no_snapshot")
    return found


@router.get("/{account_id}/positions", response_model=list[Position])
async def positions(account_id: str, c: Core) -> list[Position]:
    await c.accounts.get(account_id)
    return c.positions.positions(account_id)


@router.get("/{account_id}/orders", response_model=list[PendingOrder])
async def orders(account_id: str, c: Core) -> list[PendingOrder]:
    await c.accounts.get(account_id)
    return c.positions.orders(account_id)


# ------------------------------------------------------------------------------------------------------ versioned rules


@router.get(
    "/{account_id}/rules", response_model=RulesOverview, summary="The rules in force, the ones waiting, the history"
)
async def rules(account_id: str, c: Core) -> RulesOverview:
    return await c.accounts.rules_overview(account_id)


@router.post(
    "/{account_id}/rules", response_model=RuleVersion, status_code=201,
    summary="Ask for new rules: applied now only if no session is in progress (anti-tilt), else at the next trading day",
)  # fmt: skip
async def request_rules(account_id: str, body: AccountRules, c: Core) -> RuleVersion:
    return await c.accounts.request_rules(account_id, body)


@router.post(
    "/{account_id}/rules/{version_id}/cancel", response_model=CancelResult, summary="Withdraw a waiting change"
)
async def cancel_rules(account_id: str, version_id: str, c: Core) -> CancelResult:
    version = await c.repos.rules.get(version_id)
    if version is None or version.account_id != account_id:
        raise NotFound(f"no rule version {version_id!r} for this account", code="rule_version_not_found")
    return CancelResult(outcome=await c.accounts.cancel_rules(version_id))


# ------------------------------------------------------------------------------------------------------ the vault (write-only)


@router.get("/{account_id}/credentials", response_model=CredentialStatus, summary="Whether a password is in the vault")
async def credentials_status(account_id: str, c: Core) -> CredentialStatus:
    await c.accounts.get(account_id)
    return CredentialStatus(store=c.credentials.name, stored=await c.credentials.has(account_id))


@router.put("/{account_id}/credentials", status_code=204, summary="Put a password in the vault (never readable back)")
async def put_credentials(account_id: str, body: CredentialRequest, c: Core) -> Response:
    await c.accounts.get(account_id)
    await c.credentials.put(account_id, body.password)
    return Response(status_code=204)


@router.delete("/{account_id}/credentials", status_code=204, summary="Remove the password from the vault")
async def delete_credentials(account_id: str, c: Core) -> Response:
    await c.accounts.get(account_id)
    await c.credentials.delete(account_id)
    return Response(status_code=204)


# ------------------------------------------------------------------------------------------------------ the active account


@active_router.get("", response_model=ActiveAccountView, summary="The one account that receives automatic commands")
async def get_active(c: Core) -> ActiveAccountView:
    return ActiveAccountView(account_id=c.accounts.active_account_id)


@active_router.put("", response_model=ActiveAccountView, summary="Make a connected account the active one")
async def set_active(body: ActiveAccountRequest, c: Core) -> ActiveAccountView:
    await c.accounts.set_active(body.account_id)
    return ActiveAccountView(account_id=c.accounts.active_account_id)
