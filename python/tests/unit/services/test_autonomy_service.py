"""AutonomyService against a real database: the ladder as the human climbs it, the ARMED window, readiness lost, the halt
and what survives a restart (only the halt does)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from tests.support.harness import Harness
from tests.unit.services.test_accounts_service import exness, service
from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.readiness import Fact, ReadinessFacts
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.events import (
    AutonomyArmed,
    AutonomyDisarmed,
    AutonomyHalted,
    AutonomyModeChanged,
    AutonomyReadinessChanged,
)
from trading_os.infrastructure.database.pool import Database
from trading_os.services.accounts import AccountService
from trading_os.services.autonomy import AUTONOMY_KEY, AutonomyService
from trading_os.shared.errors import Forbidden, IllegalTransition, Unavailable

pytestmark = pytest.mark.db

M = AutonomyMode
TOLERANCE = timedelta(seconds=20)


@dataclass
class Facts:
    """A readiness the test drives: name a check in ``broken`` and it fails with that detail."""

    broken: dict[str, str] = field(default_factory=dict)
    explode: bool = False

    async def __call__(self) -> ReadinessFacts:
        if self.explode:
            raise RuntimeError("a bug in a service")
        return ReadinessFacts(
            **{
                name: Fact(ok=name not in self.broken, detail=self.broken.get(name, "ok"))
                for name in ReadinessFacts.model_fields
            }
        )


@dataclass
class Rig:
    h: Harness
    accounts: AccountService
    autonomy: AutonomyService
    account: Account
    facts: Facts
    halts: list[str]

    async def climb(self, *targets: AutonomyMode) -> None:
        for target in targets:
            await self.autonomy.arm(target)


def mode_of(autonomy: AutonomyService) -> AutonomyMode:
    """Read through a call, so the type checker does not remember an earlier assertion about a value awaits change."""
    return autonomy.mode


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


def new_service(
    h: Harness, accounts: AccountService, facts: Facts, halts: list[str], ceiling: AutonomyMode
) -> AutonomyService:
    async def record(reason: str) -> int:
        halts.append(reason)
        return 1

    return AutonomyService(
        repos=h.repos, events=h.events, clock=h.clock, accounts=accounts, ceiling=ceiling, readiness=facts,
        halt_agents=record, blocked_tolerance=TOLERANCE,
    )  # fmt: skip


async def make(h: Harness, *, max_mode: AutonomyMode = M.AUTONOMOUS, ceiling: AutonomyMode = M.AUTONOMOUS) -> Rig:
    accounts = service(h)
    created = await accounts.create(exness())
    await accounts.connect(created.id)
    await accounts.request_rules(
        created.id,
        created.rules.model_copy(update={"execution_profile": created.execution_profile.model_copy(update={"max_mode": max_mode})}),
    )  # fmt: skip
    facts = Facts()
    halts: list[str] = []
    autonomy = new_service(h, accounts, facts, halts, ceiling)
    await autonomy.start()
    return Rig(h, accounts, autonomy, await accounts.effective(created.id), facts, halts)


# ------------------------------------------------------------------------------------------------------ the ladder


async def test_it_starts_off_and_climbs_one_rung_at_a_time(h: Harness) -> None:
    rig = await make(h)
    assert mode_of(rig.autonomy) is M.OFF and not rig.autonomy.permits_entries() and not rig.autonomy.halted()
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM)
    assert mode_of(rig.autonomy) is M.CONFIRM and rig.autonomy.permits_entries()
    assert [(e.previous, e.current) for e in h.recorder.of(AutonomyModeChanged)] == [
        (M.OFF, M.OBSERVE), (M.OBSERVE, M.PAPER), (M.PAPER, M.CONFIRM),
    ]  # fmt: skip
    stored = await h.repos.state.get(AUTONOMY_KEY)
    assert stored is not None and stored["mode"] == "CONFIRM"  # every climb is on record before it counts


async def test_skipping_a_rung_or_stepping_up_through_disarm_is_refused(h: Harness) -> None:
    rig = await make(h)
    with pytest.raises(IllegalTransition) as caught:
        await rig.autonomy.arm(M.CONFIRM)
    assert caught.value.code == "skipped_rung" and mode_of(rig.autonomy) is M.OFF
    assert (await rig.autonomy.disarm(M.CONFIRM)).mode is M.OFF  # disarm is never a way up


async def test_the_ceiling_is_the_lower_of_the_process_and_the_active_account(h: Harness) -> None:
    capped_account = await make(h, max_mode=M.CONFIRM)
    await capped_account.climb(M.OBSERVE, M.PAPER, M.CONFIRM)
    with pytest.raises(Forbidden) as caught:
        await capped_account.autonomy.arm(M.ARMED)
    assert caught.value.code == "above_ceiling"
    assert await capped_account.autonomy.ceiling() is M.CONFIRM

    capped_process = AutonomyService(
        repos=h.repos, events=h.events, clock=h.clock, accounts=capped_account.accounts, ceiling=M.OBSERVE
    )
    await capped_process.start()
    await capped_process.arm(M.OBSERVE)
    with pytest.raises(Forbidden) as again:
        await capped_process.arm(M.PAPER)  # TRADING_MODE is a ceiling the account's setting cannot raise
    assert again.value.code == "above_ceiling"


async def test_with_no_active_account_nothing_above_observe_is_reachable(h: Harness) -> None:
    accounts = service(h)  # nothing created, nothing connected
    autonomy = new_service(h, accounts, Facts(), [], M.AUTONOMOUS)
    await autonomy.start()
    assert await autonomy.ceiling() is M.OBSERVE
    await autonomy.arm(M.OBSERVE)
    with pytest.raises(Forbidden):
        await autonomy.arm(M.PAPER)


async def test_the_effective_mode_of_an_account_is_the_lower_of_the_state_and_its_ceiling(h: Harness) -> None:
    rig = await make(h, max_mode=M.PAPER)
    assert rig.autonomy.effective_mode(rig.account) is M.OFF
    await rig.climb(M.OBSERVE, M.PAPER)
    assert rig.autonomy.effective_mode(rig.account) is M.PAPER
    other = rig.account.model_copy(
        update={"execution_profile": rig.account.execution_profile.model_copy(update={"max_mode": M.OBSERVE})}
    )
    assert rig.autonomy.effective_mode(other) is M.OBSERVE  # a stricter account is held back whatever the system does
    await rig.autonomy.halt("test")
    assert rig.autonomy.effective_mode(rig.account) is M.HALTED


# ------------------------------------------------------------------------------------------------------ readiness


async def test_the_automatic_rungs_say_exactly_what_blocks_them(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM)
    rig.facts.broken = {"reconciliation": "2 critical findings", "heartbeat": "agent silent for 40 s"}
    with pytest.raises(Forbidden) as caught:
        await rig.autonomy.arm(M.ARMED)
    assert caught.value.code == "not_ready" and caught.value.details["blockers"] == ["reconciliation", "heartbeat"]
    assert "reconciliation" in str(caught.value) and mode_of(rig.autonomy) is M.CONFIRM
    detail = {c["checkId"] if "checkId" in c else c["check_id"]: c["detail"] for c in caught.value.details["checks"]}
    assert detail["heartbeat"] == "agent silent for 40 s"

    rig.facts.broken = {}
    assert (await rig.autonomy.arm(M.ARMED)).mode is M.ARMED


async def test_a_change_of_verdict_is_published_once_not_at_every_evaluation(h: Harness) -> None:
    rig = await make(h)
    await rig.autonomy.readiness(fresh=True)
    await rig.autonomy.readiness(fresh=True)
    assert (
        len(h.recorder.of(AutonomyReadinessChanged)) == 1 and h.recorder.of(AutonomyReadinessChanged)[0].readiness.ready
    )
    rig.facts.broken = {"database": "down"}
    await rig.autonomy.readiness(fresh=True)
    await rig.autonomy.readiness(fresh=True)
    assert [e.readiness.blockers for e in h.recorder.of(AutonomyReadinessChanged)] == [[], ["database"]]


async def test_a_readiness_that_cannot_be_gathered_is_never_green(h: Harness) -> None:
    rig = await make(h)
    rig.facts.explode = True
    report = await rig.autonomy.readiness(fresh=True)
    assert not report.ready and "python_core" in report.blockers
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM)
    with pytest.raises(Forbidden):
        await rig.autonomy.arm(M.ARMED)


async def test_the_cached_report_is_reused_for_a_moment(h: Harness) -> None:
    rig = await make(h)
    first = await rig.autonomy.readiness(fresh=True)
    rig.facts.broken = {"database": "down"}
    assert await rig.autonomy.readiness() is first  # within the TTL
    h.clock.advance(seconds=3)
    assert not (await rig.autonomy.readiness()).ready


# ------------------------------------------------------------------------------------------------------ the ARMED window


async def test_the_armed_window_is_renewed_by_the_human_and_lapses_into_confirm(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED)
    armed_at = h.clock.now()
    assert rig.autonomy.state.lease_until == armed_at + timedelta(minutes=30)
    assert h.recorder.of(AutonomyArmed)[-1].lease_until == armed_at + timedelta(minutes=30)

    h.clock.advance(minutes=29)
    await rig.autonomy.tick()
    assert mode_of(rig.autonomy) is M.ARMED
    renewed = await rig.autonomy.renew()
    assert renewed.lease_until == h.clock.now() + timedelta(minutes=30)

    h.clock.advance(minutes=31)
    await rig.autonomy.tick()
    assert mode_of(rig.autonomy) is M.CONFIRM and rig.autonomy.state.lease_until is None  # a human is back in the loop
    assert h.recorder.of(AutonomyDisarmed)[-1].reason == "lease expired"
    assert not rig.autonomy.halted()
    with pytest.raises(IllegalTransition) as caught:
        await rig.autonomy.renew()
    assert caught.value.code == "no_lease"


async def test_renewing_needs_a_green_readiness_too(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED)
    rig.facts.broken = {"heartbeat": "silent"}
    with pytest.raises(Forbidden) as caught:
        await rig.autonomy.renew()
    assert caught.value.code == "not_ready"


@pytest.mark.parametrize("top", [M.ARMED, M.AUTONOMOUS])
async def test_a_readiness_that_stays_red_steps_an_automatic_rung_down_to_confirm(
    h: Harness, top: AutonomyMode
) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED, *([M.AUTONOMOUS] if top is M.AUTONOMOUS else []))
    rig.facts.broken = {"heartbeat": "agent silent"}
    await rig.autonomy.tick()  # the clock starts
    h.clock.advance(seconds=10)
    await rig.autonomy.tick()
    assert mode_of(rig.autonomy) is top  # still inside the tolerance: the supervisor blocks entries meanwhile
    h.clock.advance(seconds=11)
    await rig.autonomy.tick()
    assert mode_of(rig.autonomy) is M.CONFIRM
    assert h.recorder.of(AutonomyDisarmed)[-1].reason == "readiness lost: heartbeat"


async def test_a_flap_shorter_than_the_tolerance_changes_nothing(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED, M.AUTONOMOUS)
    for _ in range(3):
        rig.facts.broken = {"heartbeat": "blip"}
        await rig.autonomy.tick()
        h.clock.advance(seconds=15)
        rig.facts.broken = {}
        await rig.autonomy.tick()  # recovered: the clock is reset
        h.clock.advance(seconds=15)
    assert mode_of(rig.autonomy) is M.AUTONOMOUS


async def test_human_in_the_loop_rungs_do_not_depend_on_readiness(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM)
    rig.facts.broken = {"database": "down"}
    h.clock.advance(minutes=5)
    await rig.autonomy.tick()
    assert mode_of(rig.autonomy) is M.CONFIRM


async def test_lowering_the_ceiling_under_a_running_mode_pulls_it_down(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM)
    h.clock.advance(seconds=1)  # two rule versions never share an instant
    await rig.accounts.request_rules(
        rig.account.id,
        rig.account.rules.model_copy(update={"execution_profile": rig.account.execution_profile.model_copy(update={"max_mode": M.OBSERVE})}),
    )  # fmt: skip
    await rig.autonomy.tick()
    assert mode_of(rig.autonomy) is M.OBSERVE
    assert "ceiling lowered" in h.recorder.of(AutonomyDisarmed)[-1].reason


# ------------------------------------------------------------------------------------------------------ halt and disarm


async def test_disarm_steps_down_immediately_and_records_who_and_why(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED)
    state = await rig.autonomy.disarm(M.PAPER, reason="going to lunch", actor="user")
    assert state.mode is M.PAPER and state.lease_until is None
    assert h.recorder.of(AutonomyDisarmed)[-1].reason == "going to lunch (user)"


async def test_halt_cuts_everything_and_leaving_it_takes_an_acknowledgement(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED)
    state = await rig.autonomy.halt("reconciliation failed", actor="supervisor")
    assert state.mode is M.HALTED and rig.autonomy.halted() and not rig.autonomy.permits_entries()
    assert rig.halts == ["reconciliation failed"]  # the execution agents were told
    assert h.recorder.of(AutonomyHalted)[-1].reason == "reconciliation failed (supervisor)"

    again = await rig.autonomy.halt("second reason")  # idempotent for the state, but the agents are told again
    assert (
        again is state
        and len(h.recorder.of(AutonomyHalted)) == 1
        and rig.halts == ["reconciliation failed", "second reason"]
    )

    with pytest.raises(IllegalTransition) as halted:
        await rig.autonomy.arm(M.OBSERVE)
    assert halted.value.code == "halted"
    with pytest.raises(Forbidden) as unacknowledged:
        await rig.autonomy.disarm()
    assert unacknowledged.value.code == "ack_required"
    off = await rig.autonomy.disarm(acknowledge=True)
    assert off.mode is M.OFF  # never straight back to trading


async def test_a_halt_survives_a_restart_and_anything_else_does_not(h: Harness) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED)
    await rig.autonomy.halt("critical error")
    restarted = new_service(h, rig.accounts, rig.facts, [], M.AUTONOMOUS)
    await restarted.start()
    assert restarted.halted() and restarted.state.halted_reason == "critical error (system)"
    assert (await restarted.disarm(acknowledge=True)).mode is M.OFF

    h.recorder.clear()
    fresh = new_service(h, rig.accounts, rig.facts, [], M.AUTONOMOUS)
    await fresh.start()
    await fresh.arm(M.OBSERVE)
    await fresh.arm(M.PAPER)
    await fresh.arm(M.CONFIRM)
    await fresh.arm(M.ARMED)
    after = new_service(h, rig.accounts, rig.facts, [], M.AUTONOMOUS)
    await after.start()
    assert after.mode is M.OFF  # a restart never resumes trading
    assert "restarted while ARMED" in h.recorder.of(AutonomyDisarmed)[-1].reason
    stored = await h.repos.state.get(AUTONOMY_KEY)
    assert stored is not None and stored["mode"] == "OFF"


# ------------------------------------------------------------------------------------------------------ the store


async def test_a_step_up_that_cannot_be_recorded_is_refused_but_a_step_down_is_not(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await make(h)
    await rig.climb(M.OBSERVE, M.PAPER)

    async def broken(key: str, value: object) -> None:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(h.repos.state, "set", broken)
    with pytest.raises(Unavailable) as caught:
        await rig.autonomy.arm(M.CONFIRM)
    assert caught.value.code == "store_unavailable" and mode_of(rig.autonomy) is M.PAPER  # not changed

    assert (await rig.autonomy.disarm(M.OBSERVE)).mode is M.OBSERVE  # safety actions never wait for the database
    assert (await rig.autonomy.halt("db is down too")).mode is M.HALTED


# ------------------------------------------------------------------------------------------------------ reading


async def test_the_overview_gathers_what_the_cockpit_shows(h: Harness) -> None:
    rig = await make(h, max_mode=M.CONFIRM)
    await rig.climb(M.OBSERVE)
    await rig.autonomy.readiness(fresh=True)
    overview = await rig.autonomy.overview()
    assert overview.state.mode is M.OBSERVE and overview.ceiling is M.CONFIRM and overview.effective_mode is M.OBSERVE
    assert overview.active_account_id == rig.account.id and overview.readiness is not None and overview.readiness.ready
