"""A REPARK verdict inside CORE's fine re-park caps runs without an operator; every refusal makes no re-park call."""

import asyncio
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException

from core_common.stop_pose import REPARK_MAX_FORWARD_M, REPARK_MAX_LEFT_M
from fleet.server.trips.auto_repark import ACTOR, AutoNamedCorrection, auto_repark, evaluate_named_stop
from fleet.server.trips.trip_ports import TripConfig
from fleet.site_map import SitePlace
from fleet.traffic.trip_lease import HELD

RUN = "11111111-1111-4111-8111-111111111111"
FIT = NS(apply=lambda point: tuple(point), yaw=0.0, max=0.0)
PLACE = SitePlace(id="S3", name="S3", x=1.0, y=0.5, yaw=0.0, kind="stop", pinned=True, precision_stop=dict(
    evidence_ref="test", reference_pose=(1.0, 0.5, 0.0), longitudinal_m=0.03, lateral_m=0.03, heading_rad=0.1,
    position_uncertainty_m=0.005, heading_uncertainty_rad=0.02, max_correction_m=0.05)).model_dump(mode="json")
EVIDENCE = {"map_sha256": "a" * 64, "place": "S3"}


def state(short=0.04, **override):
    base = {"pose_frame": "map", "pose": {"x": 1.0 - short, "y": 0.5, "yaw": 0.0},
            "evidence": {"pose": {"evidence": "fresh"}, "velocity": {"evidence": "fresh"}},
            "safety": {"estop": False}, "localization": {"state": "LOCALIZED", "pose_frame": "map"}}
    return {**base, **override}


class Core:
    def __init__(self, short=0.04, refuse=None):
        self.posts, self.armed_now, self.short, self.refuse = [], False, short, refuse

    def armed(self, robot_id):
        return self.armed_now

    async def send(self, trip_id, clearance):
        self.posts.append((trip_id, clearance))
        if self.refuse:
            raise HTTPException(409, detail={"code": self.refuse})
        self.armed_now = True
        return {"accepted": True}


def trip(core, limit=1, corridor=None, camera=(0.96, 0.5), **view):
    async def check(live, evidence, place):
        if corridor:
            from fleet.hub.hub import HubError
            raise HubError("COMMAND_REJECTED", corridor)
        return {"forward_m": core.short, "site_end": [1.0, 0.5], "terminal_arc": "arc"}

    live = NS(open=True, view={"robot_id": "pinky", "trip_id": "trip", "hold": None, "lease": {"state": HELD},
                               "detail": {"named_stop_operation": {"run_id": RUN}}, **view})
    async def map_pose(robot_id):
        return NS(camera_x=camera[0], camera_y=camera[1])

    runner = NS(config=TripConfig(named_stop_auto_corrections=limit), check_named_correction=check,
                auto_named_correction=core, map_pose=map_pose)
    return runner, live


def evaluate(runner, live, snapshot):
    return asyncio.run(evaluate_named_stop(runner, live, EVIDENCE, PLACE, FIT, snapshot))


def test_correction_inside_the_caps_ends_in_tolerance():
    core = Core()
    runner, live = trip(core)
    first = evaluate(runner, live, state())
    assert first["decision"] == "REPARK" and first["auto_repark"] == "dispatched"
    (trip_id, clearance), = core.posts
    assert trip_id == "trip" and clearance.forward_m == 0.04 and clearance.nav_run_id == RUN
    assert evaluate(runner, live, state())["decision"] == "REPARK" and len(core.posts) == 1  # running: no second send
    core.armed_now = False
    assert evaluate(runner, live, state(short=0.0))["decision"] == "IN_TOLERANCE"
    assert len(core.posts) == 1


def test_the_caps_come_from_core_common():
    assert (REPARK_MAX_FORWARD_M, REPARK_MAX_LEFT_M) == (0.10, 0.06)


def test_outside_the_caps_stays_hold_without_a_call():
    core = Core(short=REPARK_MAX_FORWARD_M + 0.01)
    runner, live = trip(core)
    decision = asyncio.run(auto_repark(runner, live, EVIDENCE, {
        "decision": "REPARK", "path_preview": True, "forward_m": core.short, "site_end": [1.0, 0.5]}, state(), FIT,
        SitePlace.model_validate(PLACE).precision_stop))
    assert (decision["decision"], decision["reason"]) == ("HOLD", "outside_repark_limits") and not core.posts


def test_attempt_limit_holds_after_the_configured_corrections():
    core = Core()
    runner, live = trip(core, limit=1)
    evaluate(runner, live, state())
    core.armed_now = False  # it ended, still short
    decision = evaluate(runner, live, state())
    assert (decision["decision"], decision["reason"]) == ("HOLD", "auto_correction_limit") and len(core.posts) == 1
    runner, live = trip(core, limit=0)
    assert evaluate(runner, live, state())["reason"] == "auto_correction_limit" and len(core.posts) == 1


@pytest.mark.parametrize("case", ["estop", "hold", "closed", "lease_lost", "not_localized", "stale_pose", "corridor",
                                  "refused_by_dispatch", "no_camera", "camera_disagrees", "bad_clearance"])
def test_every_refusal_makes_no_repark_call(case):
    core = Core(refuse="NAMED_STOP_CORRECTION_REFUSED" if case == "refused_by_dispatch" else None)
    camera = {"no_camera": (None, None), "camera_disagrees": (0.96 + 0.02, 0.5)}.get(case, (0.96, 0.5))
    runner, live = trip(core, corridor="NAMED_STOP_CORRECTION_CABLE_HOLD" if case == "corridor" else None,
                        camera=camera)
    snapshot = state()
    if case == "estop":
        snapshot["safety"] = {"estop": True}
    elif case == "hold":
        live.view["hold"] = {"reason": "cancel_all"}
    elif case == "closed":
        live.open = False
    elif case == "lease_lost":
        live.view["lease"] = {"state": "LOST"}
    elif case == "not_localized":
        snapshot["localization"] = {"state": "SUSPECT", "pose_frame": "map"}
    elif case == "bad_clearance":
        live.view["detail"]["named_stop_operation"] = {"run_id": "not-a-run-id"}
    elif case == "stale_pose":
        snapshot["evidence"] = {"pose": {"evidence": "stale"}, "velocity": {"evidence": "fresh"}}
    decision = evaluate(runner, live, snapshot)
    assert decision["decision"] in ("HOLD", "WAIT")
    if case in ("no_camera", "camera_disagrees"):
        assert decision["reason"] == {"no_camera": "camera_sighting_required"}.get(case, "camera_disagrees_with_pose")
    assert len(core.posts) == (1 if case == "refused_by_dispatch" else 0)  # the dispatch's own refusal is the call


def test_the_robot_side_hook_dispatches_as_the_auto_actor(monkeypatch):
    seen = {}

    async def fake(console, runner, trip_id, clearance, *, cable_inhibited, actor):
        seen.update(trip_id=trip_id, actor=actor)

    monkeypatch.setattr("fleet.server.trips.auto_repark.dispatch_correction", fake)
    hook = AutoNamedCorrection(NS(), NS(), lambda robot: False)
    asyncio.run(hook.send("trip", None))
    assert seen == {"trip_id": "trip", "actor": ACTOR}
