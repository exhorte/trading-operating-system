"""The execution agent (EA) as it describes itself — its hello overlaid by its latest heartbeat.

Never carries the agent token. ``healthy_for_orders`` is what the Risk Engine's « execution agent healthy » check and
the readiness report read; it is deliberately strict: an agent that does not say it is fine is not fine.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from trading_os.domain.primitives import DomainModel

# Fields that are clocks, not state: a heartbeat that changes only these says nothing new.
_CLOCK_FIELDS = frozenset({"gateway_silent_ms", "last_heartbeat_ms"})
_AGENT_MAGIC = re.compile(r"-(\d+)$")


class AgentStatus(DomainModel):
    account_login: str  # the MT5 login as the agent states it (its registry key)
    agent_id: str
    agent_version: str = ""
    build_id: str | None = None
    mode: str = "observe"  # effective mode, wire vocabulary: observe | paper | confirm
    mode_ceiling: str | None = None  # the highest mode this build can ever run in
    identity: Literal["ok", "mismatch", "no_account"] | None = None
    expected_account_id: str | None = None
    broker: str | None = None
    server: str = ""
    currency: str | None = None
    trade_mode: str | None = None
    margin_mode: str | None = None
    fifo_close: bool | None = None
    leverage: int | None = None
    # The four permissions an order needs — none of them settable by code.
    terminal_trade_allowed: bool | None = None
    expert_trade_allowed: bool | None = None
    account_trade_expert: bool | None = None
    account_trade_allowed: bool | None = None
    tradable: bool | None = None  # the login is on the agent's InpTradableLogins list
    closable: bool | None = None
    halted: bool | None = None  # the agent's local kill switch
    attached_experts: list[str] = Field(
        default_factory=list
    )  # every OTHER expert in the terminal — Algo Trading arms them all
    capabilities: list[str] = Field(default_factory=list)
    gateway_silent_ms: int | None = None  # how long the agent has gone without hearing from the core
    last_heartbeat_ms: int | None = None

    def can(self, capability: str) -> bool:
        return capability in self.capabilities

    @property
    def magic_number(self) -> int | None:
        """The agent's ``InpMagicNumber``, which its id carries (``mt5-execution-agent-<magic>``): the number every order,
        position and deal it produces is stamped with. ``None`` for an id that does not follow the convention."""
        match = _AGENT_MAGIC.search(self.agent_id)
        return int(match.group(1)) if match else None

    @property
    def permissions_ok(self) -> bool:
        known = [
            self.terminal_trade_allowed,
            self.expert_trade_allowed,
            self.account_trade_expert,
            self.account_trade_allowed,
        ]
        return all(flag is not False for flag in known)

    @property
    def healthy_for_orders(self) -> bool:
        return self.identity == "ok" and self.tradable is True and self.halted is not True and self.permissions_ok

    def command_refusal(self) -> str | None:
        """Why no command may go to this agent right now, or None. Only what the agent itself reported: an absent field
        (an older agent) is not a refusal here — the agent's own barriers still apply."""
        if self.halted is True:
            return "HALTED: the agent's local kill switch is set — lifted only on the MT5 chart"
        if self.identity is not None and self.identity != "ok":
            return f"IDENTITY_REFUSED: the agent reports identity {self.identity!r} for login {self.account_login}"
        return None

    def same_state_as(self, other: AgentStatus) -> bool:
        """Equal except for clocks — what decides whether a status change is worth publishing."""
        mine = self.model_dump(exclude=set(_CLOCK_FIELDS))
        return mine == other.model_dump(exclude=set(_CLOCK_FIELDS))
