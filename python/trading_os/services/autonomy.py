"""Autonomy: the ladder, the lease, the halt, and the readiness that gates the automatic rungs (ADR 0014 / 0015).

The pure rules live in ``domain/autonomy``; this service owns the *one* state they act on and what surrounds it:

* **It always starts OFF.** Whatever the system was doing before a restart, it does not resume (ADR 0014). The one thing
  that survives is a HALT: a core that restarts after a critical error stays halted until a human acknowledges it —
  the open incident would block arming anyway, but the user should see the halt itself, not infer it.
* **Climbing is written before it is true.** Arming (a step up) is persisted first; if the store is down the climb is
  refused. Coming down — disarm, lease expiry, readiness lost, halt — takes effect at once in memory and is persisted
  best-effort: a safety action is never held up by the database.
* **ARMED is a time-boxed window the human renews** (30 minutes by default); when it lapses the system falls back to
  CONFIRM, a human back in the loop, nothing is halted. AUTONOMOUS has no window but needs readiness *continuously*:
  on either automatic rung, a readiness that stays red beyond a short tolerance drops the system to CONFIRM. A flap
  shorter than the tolerance does not — the supervisor already blocks entries (SAFE) while a fault lasts.
* **HALT cuts everything**: the state, the entries (the Risk Engine reads ``halted``), and the execution agent's local
  kill switch. Leaving it takes an explicit acknowledgement and lands on OFF — never straight back to trading.

Nothing here sends an order and nothing arms by itself: every step up is a call a human makes (or Claude never makes —
``.claude/CLAUDE.md``).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy import state as ladder
from trading_os.domain.autonomy.overview import AutonomyOverview
from trading_os.domain.autonomy.readiness import Fact, ReadinessFacts, ReadinessReport, evaluate_readiness
from trading_os.domain.autonomy.state import (
    AUTOMATIC_MODES,
    DEFAULT_LEASE,
    AutonomyMode,
    AutonomyState,
    lowest,
    rank,
)
from trading_os.domain.events import (
    AutonomyArmed,
    AutonomyDisarmed,
    AutonomyHalted,
    AutonomyModeChanged,
    AutonomyReadinessChanged,
)
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.accounts import AccountService
from trading_os.shared.errors import Forbidden, NotFound, Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

AUTONOMY_KEY = "autonomy"
BLOCKED_TOLERANCE = timedelta(seconds=20)  # how long a red readiness may last on an automatic rung before stepping down
READINESS_TTL = timedelta(seconds=2)

ReadinessProvider = Callable[[], Awaitable[ReadinessFacts]]
HaltAgents = Callable[[str], Awaitable[int]]


class AutonomyService:
    def __init__(
        self,
        *,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        accounts: AccountService,
        ceiling: AutonomyMode = AutonomyMode.OBSERVE,
        readiness: ReadinessProvider | None = None,
        halt_agents: HaltAgents | None = None,
        lease: timedelta = DEFAULT_LEASE,
        blocked_tolerance: timedelta = BLOCKED_TOLERANCE,
    ) -> None:
        self._repos = repos
        self._events = events
        self._clock = clock
        self._accounts = accounts
        self._global_ceiling = ceiling  # TRADING_MODE: the highest rung this whole process may ever reach
        self._facts = readiness
        self._halt_agents = halt_agents
        self._lease = lease
        self._tolerance = blocked_tolerance
        self._state = ladder.initial_state(clock.now())
        self._report: ReadinessReport | None = None
        self._blocked_since: datetime | None = None
        self._lock = asyncio.Lock()

    def wire(self, *, readiness: ReadinessProvider, halt_agents: HaltAgents) -> None:
        """The readiness facts come from services built after this one; the container connects them here."""
        self._facts = readiness
        self._halt_agents = halt_agents

    # ------------------------------------------------------------------------------------------ reading
    @property
    def state(self) -> AutonomyState:
        return self._state

    @property
    def mode(self) -> AutonomyMode:
        return self._state.mode

    def permits_entries(self) -> bool:
        return self._state.permits_entries

    def halted(self) -> bool:
        return self._state.mode is AutonomyMode.HALTED

    def ceiling_for(self, account: Account) -> AutonomyMode:
        """The highest rung this account may reach: the process-wide ceiling and the account's own ``max_mode``."""
        return lowest(self._global_ceiling, account.execution_profile.max_mode)

    def effective_mode(self, account: Account) -> AutonomyMode:
        """What the account is really in: the lower of the system's state and the account's ceiling (HALTED stays HALTED)."""
        return lowest(self._state.mode, self.ceiling_for(account))

    async def ceiling(self) -> AutonomyMode:
        """The highest rung reachable *now*: that of the active account — and with no active account, OBSERVE."""
        active_id = self._accounts.active_account_id
        if active_id is None:
            return lowest(self._global_ceiling, AutonomyMode.OBSERVE)
        try:
            return self.ceiling_for(await self._accounts.effective(active_id))
        except NotFound:
            return lowest(self._global_ceiling, AutonomyMode.OBSERVE)

    async def overview(self) -> AutonomyOverview:
        ceiling = await self.ceiling()
        return AutonomyOverview(
            state=self._state,
            ceiling=ceiling,
            effective_mode=lowest(self._state.mode, ceiling),
            active_account_id=self._accounts.active_account_id,
            readiness=self._report,
        )

    # ------------------------------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Begin OFF, whatever came before — except a halt, which stays until a human acknowledges it."""
        now = self._clock.now()
        self._state = ladder.initial_state(now)
        previous: AutonomyState | None = None
        try:
            stored = await self._repos.state.get(AUTONOMY_KEY)
            previous = AutonomyState.model_validate(stored) if isinstance(stored, dict) else None
        except Unavailable:
            logger.warning("autonomy: the stored state could not be read, starting OFF")
        except ValueError:
            logger.warning("autonomy: the stored state is unreadable, starting OFF")
        if previous is not None and previous.mode is AutonomyMode.HALTED:
            self._state = previous
            logger.warning("autonomy: still HALTED from before the restart (%s)", previous.halted_reason)
        elif previous is not None and previous.mode in AUTOMATIC_MODES:
            await self._events.publish(
                AutonomyDisarmed(
                    account_id=self._accounts.active_account_id, mode=AutonomyMode.OFF,
                    reason=f"the core restarted while {previous.mode.value}: a restart never resumes trading",
                )
            )  # fmt: skip
        await self._persist(self._state, required=False)

    # ------------------------------------------------------------------------------------------ readiness
    async def readiness(self, *, fresh: bool = False) -> ReadinessReport:
        now = self._clock.now()
        if not fresh and self._report is not None and now - self._report.evaluated_at < READINESS_TTL:
            return self._report
        try:
            facts = await self._facts() if self._facts is not None else ReadinessFacts()
        except Exception as error:  # fail closed on any bug or outage while gathering — never « ready » by accident
            logger.exception("autonomy: the readiness facts could not be gathered")
            facts = ReadinessFacts(
                python_core=Fact(ok=False, detail=f"readiness could not be gathered: {type(error).__name__}")
            )
        report = evaluate_readiness(facts, now)
        previous = self._report
        self._report = report
        if previous is None or (previous.ready, previous.blockers) != (report.ready, report.blockers):
            await self._events.publish(
                AutonomyReadinessChanged(account_id=self._accounts.active_account_id, readiness=report)
            )
        return report

    # ------------------------------------------------------------------------------------------ gestures
    async def arm(self, target: AutonomyMode, *, actor: str = "user") -> AutonomyState:
        """Climb exactly one rung. The automatic rungs need a green readiness *now*, evaluated for this call."""
        async with self._lock:
            now = self._clock.now()
            needs_ready = target in AUTOMATIC_MODES
            report = await self.readiness(fresh=True) if needs_ready else self._report
            try:
                new = ladder.arm(
                    self._state, target, ceiling=await self.ceiling(), now=now,
                    ready=report.ready if (needs_ready and report) else True, lease=self._lease,
                )  # fmt: skip
            except Forbidden as error:
                if error.code == "not_ready" and report is not None:
                    raise Forbidden(
                        "autonomy readiness is not green: " + ", ".join(report.blockers),
                        code="not_ready",
                        details={
                            "blockers": report.blockers,
                            "checks": [c.model_dump(mode="json") for c in report.checks if not c.ok],
                        },
                    ) from None
                raise
            logger.info("autonomy: %s → %s armed by %s", self._state.mode.value, target.value, actor)
            return await self._transition(new, required=True, readiness=report)

    async def renew(self, *, actor: str = "user") -> AutonomyState:
        """Renew the ARMED window. Only worth doing while the system could be armed afresh: readiness must be green."""
        async with self._lock:
            report = await self.readiness(fresh=True)
            if not report.ready:
                raise Forbidden(
                    "autonomy readiness is not green: " + ", ".join(report.blockers),
                    code="not_ready",
                    details={"blockers": report.blockers},
                )
            new = ladder.renew_lease(self._state, now=self._clock.now(), lease=self._lease)
            logger.info("autonomy: ARMED window renewed by %s until %s", actor, new.lease_until)
            return await self._transition(new, required=True, readiness=report)

    async def disarm(
        self,
        target: AutonomyMode = AutonomyMode.OBSERVE,
        *,
        acknowledge: bool = False,
        reason: str | None = None,
        actor: str = "user",
    ) -> AutonomyState:
        """Step down — always allowed, immediate. From HALTED, an explicit acknowledgement lands on OFF."""
        async with self._lock:
            new = ladder.disarm(
                self._state, now=self._clock.now(), target=target, acknowledge=acknowledge,
                reason=f"{reason} ({actor})" if reason else None,
            )  # fmt: skip
            return await self._transition(new, required=False)

    async def halt(self, reason: str, *, actor: str = "system") -> AutonomyState:
        """Cut everything: the state, the entries, the execution agent's kill switch. Idempotent — and the agents are
        told again even if the state was already HALTED (the first attempt may have found the link down)."""
        async with self._lock:
            new = ladder.halt(self._state, reason=f"{reason} ({actor})", now=self._clock.now())
            state = await self._transition(new, required=False)
        if self._halt_agents is not None:
            try:
                told = await self._halt_agents(reason)
                logger.warning("autonomy: HALT (%s, by %s) — %d execution agent(s) told", reason, actor, told)
            except Exception:  # the halt itself stands; a missing agent is reported by the supervisor, not hidden here
                logger.exception("autonomy: HALT could not reach the execution agents")
        return state

    # ------------------------------------------------------------------------------------------ the periodic duty
    async def tick(self) -> None:
        """Every couple of seconds: lease expiry, a lowered ceiling, and readiness lost on an automatic rung."""
        async with self._lock:
            now = self._clock.now()
            expired = ladder.expire_lease_if_due(self._state, now)
            if expired is not self._state:
                await self._transition(expired, required=False)
            ceiling = await self.ceiling()
            clamped = ladder.clamp_to_ceiling(self._state, ceiling, now)
            if clamped is not self._state:
                await self._transition(clamped, required=False)
            if self._facts is None:
                return
            report = await self.readiness(fresh=True)
            if self._state.mode not in AUTOMATIC_MODES or report.ready:
                self._blocked_since = None
                return
            self._blocked_since = self._blocked_since or now
            if now - self._blocked_since >= self._tolerance:
                lowered = ladder.disarm(
                    self._state, now=now, target=AutonomyMode.CONFIRM,
                    reason="readiness lost: " + ", ".join(report.blockers),
                )  # fmt: skip
                self._blocked_since = None
                await self._transition(lowered, required=False)

    # ------------------------------------------------------------------------------------------ internals
    async def _transition(
        self, new: AutonomyState, *, required: bool, readiness: ReadinessReport | None = None
    ) -> AutonomyState:
        """Make ``new`` the state. ``required``: persist first and refuse if that fails (a step up must be on record);
        otherwise apply at once and persist best-effort (a safety action never waits for the database)."""
        old = self._state
        if new is old:
            return old
        if required:
            await self._persist(new, required=True)
            self._state = new
        else:
            self._state = new
            await self._persist(new, required=False)
        await self._publish(old, new, readiness)
        return new

    async def _persist(self, state: AutonomyState, *, required: bool) -> None:
        try:
            await self._repos.state.set(AUTONOMY_KEY, state.model_dump(mode="json"))
        except Unavailable as error:
            if required:
                raise Unavailable(
                    "the autonomy state could not be recorded, so it was not changed", code="store_unavailable"
                ) from error
            logger.error("autonomy: the new state could not be persisted (%s)", error.safe_message)

    async def _publish(self, old: AutonomyState, new: AutonomyState, readiness: ReadinessReport | None) -> None:
        account_id = self._accounts.active_account_id
        reason = new.last_transition.reason if new.last_transition else ""
        if new.mode is not old.mode:
            await self._events.publish(
                AutonomyModeChanged(
                    account_id=account_id, previous=old.mode, current=new.mode, reason=reason, lease_until=new.lease_until
                )
            )  # fmt: skip
            if new.mode is AutonomyMode.HALTED:
                await self._events.publish(AutonomyHalted(account_id=account_id, reason=new.halted_reason or reason))
            elif rank(new.mode) < rank(old.mode):
                await self._events.publish(AutonomyDisarmed(account_id=account_id, mode=new.mode, reason=reason))
            elif new.mode in AUTOMATIC_MODES:
                await self._events.publish(
                    AutonomyArmed(account_id=account_id, mode=new.mode, lease_until=new.lease_until, readiness=readiness)
                )  # fmt: skip
        elif new.lease_until != old.lease_until and new.mode is AutonomyMode.ARMED:
            await self._events.publish(
                AutonomyArmed(account_id=account_id, mode=new.mode, lease_until=new.lease_until, readiness=readiness)
            )  # a renewed window
