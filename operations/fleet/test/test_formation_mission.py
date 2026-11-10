"""D-1002 formation mission: lane fit before arming, leader trip job after arming, one ends with the other."""

from __future__ import annotations

import asyncio

import pytest

from fleet.hub.hub import HubError
from fleet.server.formation_mission import (FormationMission, FormationMissionRequest, lane_fit,
                                            leader_job_open, min_lane_spacing)


def _fit(formation, spacing=0.6, max_speed=0.18, followers=1):
    return lane_fit(formation, spacing, max_speed, followers)


def test_single_file_formations_fit_the_lane_and_lateral_ones_do_not():
    assert _fit("TRAIL")["spacing_floor"] == pytest.approx(0.57)
    assert _fit("COLUMN", followers=3)["followers"] == 3
    for shape in ("LINE", "V", "GRID", "CIRCLE"):
        with pytest.raises(HubError) as exc:
            _fit(shape)
        assert exc.value.code == "FORMATION_LANE_UNFIT"
    with pytest.raises(HubError) as exc:
        _fit("DIAMOND")
    assert exc.value.code == "INVALID_FORMATION"


def test_spacing_must_cover_the_stopping_gap_at_the_follower_speed():
    """body 0.2 + speed x 1.5 s hold latency (D-559 SIM 1.2 s) + 0.1 margin; faster followers need more room."""
    assert min_lane_spacing(0.18) == pytest.approx(0.57)
    assert min_lane_spacing(0.30) == pytest.approx(0.75)
    with pytest.raises(HubError, match="stopping gap"):
        _fit("TRAIL", spacing=0.6, max_speed=0.30)
    assert _fit("TRAIL", spacing=0.8, max_speed=0.30)["spacing"] == 0.8
    with pytest.raises(HubError, match="followers"):
        _fit("COLUMN", followers=4)
    with pytest.raises(HubError, match="followers"):
        _fit("COLUMN", followers=0)


class _Store:
    """The ledger row the mission watches; a HOLD keeps the lease entry, so the row status is the signal."""

    def __init__(self, status="RUNNING"):
        self.rows = {"m-1": {"status": status}}

    def get(self, mission_id):
        return self.rows.get(mission_id)


def test_leader_job_is_open_only_while_its_row_is_active():
    store = _Store("READY")
    assert leader_job_open(store, "m-1")
    store.rows["m-1"]["status"] = "RUNNING"
    assert leader_job_open(store, "m-1")
    store.rows["m-1"]["status"] = "HOLD"           # FOR-004 cancelled the leader; the lease entry still exists
    assert not leader_job_open(store, "m-1")
    store.rows["m-1"]["status"] = "GOAL_CONFIRMED"  # arrived
    assert not leader_job_open(store, "m-1")
    assert not leader_job_open(store, "gone")


class _Console:
    def __init__(self) -> None:
        self.calls: list = []
        self.status = {"active": False, "state": "IDLE", "reason": None}

    async def formation_start(self, leader, formation, spacing, max_speed, members=None):
        self.calls.append(("start", leader, formation, spacing, max_speed, tuple(members)))
        self.status = {"active": True, "state": "RUNNING", "reason": None}
        return dict(self.status)

    async def formation_stop(self):
        self.calls.append(("stop",))
        self.status = {"active": False, "state": "STOPPED", "reason": self.status.get("reason")}
        return dict(self.status)

    def formation_status(self):
        return dict(self.status)


def _request(**over):
    body = {"leader": "rosy_01", "members": ["rosy_01", "rosy_02"], "formation": "TRAIL",
            "steps": [{"to": "east_end", "via": []}]}
    body.update(over)
    return FormationMissionRequest(**body)


def _mission(console, store, create_job, period_s=0.01):
    async def job_open(mission_id):
        return leader_job_open(store, mission_id)
    return FormationMission(console, create_job, job_open, period_s=period_s)


async def _create_job(leader, steps, principal_id):
    return {"mission_id": "m-1"}


def test_lane_unfit_is_refused_before_any_robot_is_armed():
    console = _Console()
    mission = _mission(console, _Store(), _create_job)
    with pytest.raises(HubError) as exc:
        asyncio.run(mission.start(_request(formation="LINE"), "op"))
    assert exc.value.code == "FORMATION_LANE_UNFIT" and console.calls == []
    assert mission.status() == {"active": False}


def test_followers_arm_first_then_the_leader_gets_a_trip_job_and_a_held_job_ends_the_mission():
    console, store, jobs = _Console(), _Store(), []

    async def create_job(leader, steps, principal_id):
        jobs.append((leader, steps, principal_id))
        return {"mission_id": "m-1"}

    async def scenario():
        mission = _mission(console, store, create_job)
        view = await mission.start(_request(), "op")
        assert view["active"] and view["mission_id"] == "m-1" and view["formation"] == "TRAIL"
        assert console.calls == [("start", "rosy_01", "TRAIL", 0.6, 0.18, ("rosy_01", "rosy_02"))]
        assert jobs == [("rosy_01", [{"to": "east_end", "via": []}], "op")]
        with pytest.raises(HubError) as exc:  # one formation mission at a time
            await mission.start(_request(), "op")
        assert exc.value.code == "FORMATION_ACTIVE"
        await asyncio.sleep(0.05)
        assert mission.status()["state"] == "RUNNING"  # the job row is still RUNNING: nothing ends
        # A follower was lost: FOR-004 HOLD cancelled the leader's navigation, the step trip ended and the
        # ledger row went to HOLD while the lease entry stays (job_trip_steps.tick -> stop_job).
        console.status.update(state="HOLDING", reason="follower_lost:rosy_02")
        store.rows["m-1"]["status"] = "HOLD"
        for _ in range(100):
            if mission.status()["state"] == "ENDED":
                break
            await asyncio.sleep(0.01)
        ended = mission.status()
        assert ended["state"] == "ENDED" and ended["end_reason"] == "follower_lost:rosy_02"
        assert console.calls[-1] == ("stop",) and not ended["active"]

    asyncio.run(scenario())


def test_a_refused_leader_job_disarms_the_followers():
    console = _Console()

    async def create_job(leader, steps, principal_id):
        raise ValueError("TRIP_UNKNOWN_PLACE")

    mission = _mission(console, _Store(), create_job)
    with pytest.raises(ValueError):
        asyncio.run(mission.start(_request(), "op"))
    assert [c[0] for c in console.calls] == ["start", "stop"]
    assert mission.status() == {"active": False}


def test_an_unreadable_ledger_ends_the_mission_instead_of_leaving_followers_armed():
    console = _Console()

    async def broken(mission_id):
        raise RuntimeError("database is locked")

    async def scenario():
        mission = FormationMission(console, _create_job, broken, period_s=0.001)
        await mission.start(_request(), "op")
        for _ in range(200):
            if mission.status()["state"] == "ENDED":
                break
            await asyncio.sleep(0.005)
        ended = mission.status()
        assert ended["state"] == "ENDED" and ended["end_reason"] == "ledger_unreadable"
        assert console.calls[-1] == ("stop",)

    asyncio.run(scenario())


def test_stop_records_the_operator_and_releases_the_formation():
    console = _Console()

    async def scenario():
        mission = _mission(console, _Store(), _create_job)
        await mission.start(_request(), "op")
        view = await mission.stop()
        assert view["state"] == "ENDED" and view["end_reason"] == "stopped" and not view["active"]
        assert console.calls[-1] == ("stop",)

    asyncio.run(scenario())
