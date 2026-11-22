"""The pilot (ADR 0043): a system that is autonomous once launched.

At start-up, and then every few seconds, it brings the system to the mode ``AUTOPILOT_TARGET`` names, by the very gestures a person would make and
with the very same checks:

1. the active account is attached — without a password: the terminal is already logged in (the core never keeps one);
2. the start-up sequence runs, up to ``CONFIRM`` at most (``StartupService.begin``: checks, reconciliation, the climb);
3. then one rung at a time — ``CONFIRM → ARMED → AUTONOMOUS`` — each through ``StartupService.authorize_automatic``, which refuses while a single
   condition is red. A refusal is not an error: the next pass tries again.

It keeps the system there: if the readiness drops (the autonomy service brings the system down to ``CONFIRM``), it climbs back once every
condition is green again; an ``ARMED`` target has its lease renewed before it lapses.

What it never does: pilot a real-money (``LIVE``) account — it stops and says so; act while the system is halted; climb above the ceiling (the ladder
refuses, as it refuses a person). **A person who disarms or halts pauses it** — the next « démarrer le système », or a restart of the core, resumes it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from trading_os.domain.accounts.models import Environment
from trading_os.domain.autonomy.state import AUTOMATIC_MODES, AutonomyMode, lowest, rank
from trading_os.domain.primitives import DomainModel
from trading_os.domain.system.startup import StartupRunState
from trading_os.services.accounts import AccountService
from trading_os.services.autonomy import AutonomyService
from trading_os.services.startup import StartupService
from trading_os.shared.errors import TradingOsError
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

RETRY_START_AFTER = timedelta(seconds=60)  # a start-up that stopped below its target is not re-run on every pass
RENEW_WHEN_LEFT = timedelta(minutes=5)  # an ARMED target: renew the lease when this little of it is left


class AutopilotStatus(DomainModel):
    target: AutonomyMode
    active: bool  # a target above OFF and not paused
    paused_reason: str | None = None
    last_step: str = "not run yet"
    last_step_at: datetime | None = None


class Autopilot:
    def __init__(
        self,
        *,
        target: AutonomyMode,
        accounts: AccountService,
        autonomy: AutonomyService,
        startup: StartupService,
        clock: Clock,
    ) -> None:
        self._target = target
        self._accounts = accounts
        self._autonomy = autonomy
        self._startup = startup
        self._clock = clock
        self._paused: str | None = None
        self._last_step = "not run yet"
        self._last_step_at: datetime | None = None
        self._next_start_at: datetime | None = None

    # ------------------------------------------------------------------------------------------ what a person does to it
    def pause(self, reason: str) -> None:
        if self._target is not AutonomyMode.OFF and self._paused is None:
            logger.info("autopilot: paused — %s", reason)
        self._paused = reason

    def resume(self) -> None:
        if self._paused is not None:
            logger.info("autopilot: resumed")
        self._paused = None
        self._next_start_at = None

    def status(self) -> AutopilotStatus:
        return AutopilotStatus(
            target=self._target,
            active=self._target is not AutonomyMode.OFF and self._paused is None,
            paused_reason=self._paused,
            last_step=self._last_step,
            last_step_at=self._last_step_at,
        )

    # ------------------------------------------------------------------------------------------ one pass
    async def tick(self) -> None:
        if self._target is AutonomyMode.OFF or self._paused is not None:
            return
        if self._autonomy.halted():
            self._note("the system is halted: nothing is done until a person acknowledges the halt")
            return
        account_id = self._accounts.active_account_id
        if account_id is None:
            self._note("no active account: nothing to pilot")
            return
        if self._accounts.session(account_id) is None:
            try:
                await self._accounts.connect(account_id)  # no password: the terminal is already logged in
            except TradingOsError as error:
                self._note(f"could not attach {account_id}: {error.safe_message}")
                return
            self._note(f"attached {account_id}")
            return  # the market, the agent and the reconciliation need a few passes before anything else is asked
        account = await self._accounts.effective(account_id)
        if account.environment is Environment.LIVE:
            self.pause("a real-money account is never piloted: the trader starts it")
            self._note("real-money account: the pilot stays out of it")
            return
        mode = self._autonomy.effective_mode(account)
        target = lowest(self._target, await self._autonomy.ceiling())
        if rank(mode) >= rank(target):
            await self._keep_lease(mode)
            return
        if mode in (AutonomyMode.CONFIRM, AutonomyMode.ARMED) and rank(target) > rank(mode):
            try:
                reached, _plan = await self._startup.authorize_automatic()
            except TradingOsError as error:
                self._note(f"{mode.value} → next rung held back: {error.safe_message}")
                return
            self._note(f"climbed to {reached.value}")
            return
        await self._start(lowest(target, AutonomyMode.CONFIRM))

    async def _start(self, start_target: AutonomyMode) -> None:
        now = self._clock.now()
        if self._next_start_at is not None and now < self._next_start_at:
            return
        try:
            run = await self._startup.begin(start_target)
        except TradingOsError as error:
            self._note(f"start-up to {start_target.value} refused: {error.safe_message}")
            self._next_start_at = now + RETRY_START_AFTER
            return
        if run.state is StartupRunState.RUNNING:
            self._note(f"start-up to {start_target.value} running")
        self._next_start_at = now + RETRY_START_AFTER

    async def _keep_lease(self, mode: AutonomyMode) -> None:
        state = self._autonomy.state
        if mode is not AutonomyMode.ARMED or mode not in AUTOMATIC_MODES or state.lease_until is None:
            return
        if state.lease_until - self._clock.now() > RENEW_WHEN_LEFT:
            return
        try:
            await self._autonomy.renew(actor="autopilot")
        except TradingOsError as error:
            self._note(f"ARMED lease not renewed: {error.safe_message}")
            return
        self._note("ARMED lease renewed")

    def _note(self, step: str) -> None:
        if step != self._last_step:
            logger.info("autopilot: %s", step)
        self._last_step = step
        self._last_step_at = self._clock.now()
