"""Admission using fresh obstacle-only observations of a disconnected peer."""
from types import SimpleNamespace

import pytest

from fleet.localization import trust
from fleet.server.offline_marker import OfflineMarkerClearance
from fleet.server.sightings import SightingService, SightingSource
from core_common.protocol.sightings import SiteSightingPayload
from rosy.world.state.projections.map_pose import MapPoseConfig
from test_server_traffic import _rotated_site_console, _standing, _loc, run

RID, MAP = "rosy_02", "world_261026"


@pytest.fixture
def rig():
    now = [100.0]
    revision = ["rev"]
    version = [8]
    sources = [
        SightingSource(name, name + "-key", (RID, "rosy_03"), MAP, "base", (8, 9, 10, 11),
                       robot_markers=((RID, 42), ("rosy_03", 43)))
        for name in ("north", "east")]
    seen = SightingService(sources, known_robot_ids=(RID, "rosy_03"), clock=lambda: now[0],
                           approved_revision=lambda _: revision[0])
    record = SimpleNamespace(map_id=MAP, calibration_revision="rev", track_bounds_m=(-2., -2., 2., 2.))
    clearance = OfflineMarkerClearance(seen, lambda: (version[0], SimpleNamespace(map_id=MAP)),
                                      MapPoseConfig(), lambda _: record, clock=lambda: now[0], wall=lambda: now[0])
    console, mover, peer = _rotated_site_console(_standing(RID, (0, 0), _loc()), None)
    async def unavailable():
        raise OSError("peer offline")
    peer.state = unavailable
    console._site_marker_clearance = clearance
    console._remember([{"robot_id": RID, "online": False, "state": None}])
    def observe(y=0.9, age=0.05, seq=2, source="north"):
        payload = SiteSightingPayload(robot_id=RID, map_id=MAP, x=0., y=y, yaw=0., captured_at=now[0]-age,
                                      seq=seq, calibration_revision="rev", calibration_source="approved_record",
                                      processor_revision="marker")
        clearance.observe(seen.accept("Bearer " + source + "-key", payload))
    return SimpleNamespace(console=console, mover=mover, now=now, version=version, revision=revision,
                           see=observe, clear=clearance, seen=seen)


def test_fleet_goal_passes_with_two_stationary_markers_after_the_last_good_robot_state(rig):
    rig.see(age=.25, seq=1)
    rig.see()
    assert rig.console._verdict(RID) == trust.UNTRUSTED
    assert "queued" not in run(rig.console.goal("rosy_01", 2, 0))
    first = rig.clear.evidence(RID)
    assert first["reason"] == "peer_clear" and first["min_route_distance_m"] == pytest.approx(1.1)
    assert first["observations"][0]["age_s"] == pytest.approx(.05)
    rig.now[0] += .07
    run(rig.console.goal("rosy_01", 2, 0))
    assert rig.clear.evidence(RID)["observations"][0]["age_s"] == pytest.approx(.12)
    assert first["observations"][0]["age_s"] == pytest.approx(.05)
    assert rig.console._site_mover_pose(RID) is None and rig.console._site_obstacle_pose(RID) is None


@pytest.mark.parametrize("problem", ["single", "stale", "future", "new_map", "revision", "roster",
                                     "near", "aged_near", "moved", "out_of_bounds", "conflict", "claim", "pin", "no_route"])
def test_fleet_holds_on_unproven_or_intersecting_peer_geometry(rig, problem):
    y = -.05 if problem == "near" else .05 if problem == "aged_near" else 3.0 if problem == "out_of_bounds" else .9
    if problem != "single":
        rig.see(y=y if problem != "moved" else -.2, age=.35, seq=1)
    rig.see(y=y, age=.2 if problem == "aged_near" else .05)
    if problem == "stale":
        rig.now[0] += .5
    elif problem == "future":
        rig.now[0] -= .12
    elif problem == "new_map":
        rig.version[0] += 1
    elif problem == "revision":
        rig.revision[0] = "removed"
    elif problem == "roster":
        rig.seen.retarget([])
    elif problem == "conflict":
        rig.now[0] += .1
        rig.see(y=-.8, source="east", age=.1, seq=3)
        rig.now[0] += .15
        rig.see(y=-.8, source="east", age=.1, seq=4)
    elif problem == "claim":
        rig.console._goal_busy.add(RID)
    elif problem == "pin":
        rig.console._site_obstacle_pose = lambda _: (MAP, 2., 2., 0.)
    elif problem == "no_route":
        rig.console._site_mover_pose = lambda _: None
    result = run(rig.console.goal("rosy_01", 2, 0))
    assert result["queued"] is True and result["blocked_by"] == RID


def _see_other(rig, seq, source="north", age=None):
    age = (.05 if source == "north" else .04) if age is None else age   # readback must strictly advance
    payload = SiteSightingPayload(robot_id="rosy_03", map_id=MAP, x=1.5, y=1.5, yaw=0., captured_at=rig.now[0]-age,
                                  seq=seq, calibration_revision="rev", calibration_source="approved_record",
                                  processor_revision="marker")
    rig.clear.observe(rig.seen.accept("Bearer " + source + "-key", payload))


def _hold_still(rig, y, seconds, last_age):
    seq = 1
    for _ in range(int(seconds / .5)):
        rig.see(y=y, age=.05, seq=seq)
        rig.now[0] += .5
        seq += 1
    rig.see(y=y, age=last_age, seq=seq)


def test_parked_disconnected_peer_is_a_static_obstacle_after_the_hold(rig):
    _hold_still(rig, .3, 2.5, .2)
    assert "queued" not in run(rig.console.goal("rosy_01", 2, 0))
    obs = rig.clear.evidence(RID)["observations"][0]
    assert obs["uncertainty_m"] == pytest.approx(.02) and obs["still_s"] >= 2.0


def test_parked_peer_stays_usable_past_the_moving_frame_age_limit(rig):
    # Live camera: ~0.25 s latency + ~0.35 s period, so a check can see a 0.55 s old frame.
    _hold_still(rig, .3, 2.5, .05)
    rig.now[0] += .5
    assert "queued" not in run(rig.console.goal("rosy_01", 2, 0))
    assert rig.clear.evidence(RID)["observations"][0]["age_s"] == pytest.approx(.55)
    rig.now[0] += .5                      # past the 1.0 s sighting lease: no usable marker
    result = run(rig.console.goal("rosy_01", 2, 0))
    assert result["queued"] is True and rig.clear.evidence(RID)["reason"] == "approved_marker_unavailable"


def test_young_peer_marker_older_than_the_frame_age_limit_is_unavailable(rig):
    rig.see(y=.9, age=.35, seq=1)
    rig.see(y=.9, age=.05, seq=2)
    rig.now[0] += .5
    result = run(rig.console.goal("rosy_01", 2, 0))
    assert result["queued"] is True and rig.clear.evidence(RID)["reason"] == "approved_marker_unavailable"


@pytest.mark.parametrize("problem", ["young", "moved", "gap", "new_map", "processor"])
def test_disconnected_peer_keeps_the_speed_allowance_until_it_has_stayed_still(rig, problem):
    # Same spot (0.28 m from route at y=-0.2): parked (0.22 m) clears, young (0.34 m) blocks.
    if problem in ("gap", "new_map", "processor"):
        _hold_still(rig, .08, 2.5, .05)
        rig.now[0] += .5
        if problem == "gap":
            rig.now[0] += 1.0         # > STATIC_MAX_GAP_S (1.2 s) since the last sighting: the run restarts
        elif problem == "new_map":
            rig.version[0] += 1
            rig.see(y=.08, age=.4, seq=20)
        else:
            rig.clear.still[(RID, "north")]["basis"] = ("other",)
        rig.see(y=.08, age=.2, seq=21)
    elif problem == "moved":
        _hold_still(rig, .08, 2.5, .05)
        rig.now[0] += .5
        rig.see(y=.11, age=.05, seq=20)
        rig.now[0] += .3
        rig.see(y=.11, age=.2, seq=21)
    else:
        rig.see(y=.08, age=.35, seq=1)
        rig.see(y=.08, age=.2, seq=2)
    result = run(rig.console.goal("rosy_01", 2, 0))
    assert result["queued"] is True and result["blocked_by"] == RID


def _camera_live_without_peer(rig, seconds, last_seen_ago=None):
    """rosy_03 keeps arriving on both sources every 0.35 s; RID was last seen last_seen_ago before now."""
    if last_seen_ago is not None:
        rig.see(y=.3, age=last_seen_ago, seq=1)
    seq, t = 100, 0.
    while t < seconds:
        for source in ("north", "east"):
            _see_other(rig, seq, source)
            seq += 1
        rig.now[0] += .35
        t += .35
    for source in ("north", "east"):
        _see_other(rig, seq, source)
        seq += 1


def test_offline_peer_taken_off_the_floor_stops_blocking_once_live_cameras_miss_it(rig):
    _camera_live_without_peer(rig, 5.5)
    assert "queued" not in run(rig.console.goal("rosy_01", 2, 0))
    decision = rig.clear.evidence(RID)
    assert decision["reason"] == "peer_absent_from_track" and decision["absent_s"] >= 5.0


@pytest.mark.parametrize("problem", ["recently_seen", "camera_dead", "camera_restarted", "one_source_silent"])
def test_missing_offline_peer_still_blocks_without_proof_it_left(rig, problem):
    if problem == "recently_seen":
        _camera_live_without_peer(rig, 5.5, last_seen_ago=0.05)
        rig.see(y=.3, age=.05, seq=2)          # keep it in view, then let it age out briefly
        rig.now[0] += 2.0
        for source in ("north", "east"):
            _see_other(rig, 900 + len(source), source)
    elif problem == "camera_dead":
        _camera_live_without_peer(rig, 5.5)
        rig.now[0] += 1.5                       # no frames from either camera for longer than the lease
    elif problem == "camera_restarted":
        _see_other(rig, 1, "north")
        _see_other(rig, 2, "east")
        rig.now[0] += 3.0                       # stream gap: absence counts again from the restart
        _camera_live_without_peer(rig, 2.0)
    else:
        seq = 100
        for _ in range(17):
            _see_other(rig, seq, "north")
            seq += 1
            rig.now[0] += .35
        _see_other(rig, seq, "north")
    result = run(rig.console.goal("rosy_01", 2, 0))
    assert result["queued"] is True and result["blocked_by"] == RID


def test_parked_marker_vs_pin_tolerates_marker_parallax_without_false_conflict(rig):
    _hold_still(rig, .3, 2.5, .2)
    rig.console._site_obstacle_pose = lambda _rid: (MAP, 0.0, 0.325, 0.0)  # 2.5 cm parallax vs parked marker
    assert "queued" not in run(rig.console.goal("rosy_01", 2, 0))
    assert rig.clear.evidence(RID)["reason"] == "peer_clear"

    rig.console._site_obstacle_pose = lambda _rid: (MAP, 0.0, 0.45, 0.0)   # 15 cm mismatch still conflicts
    held = run(rig.console.goal("rosy_01", 2, 0))
    assert held["queued"] is True and rig.clear.evidence(RID)["reason"] == "peer_pose_conflict"
