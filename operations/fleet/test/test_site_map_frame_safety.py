"""D-1010: a site map frame is never mixed into another — the active body is verified against
its stored sha256, a free goal is bound to the plan's map version and to both frames of the
conversion, and the frames of a sent goal are recorded for the audit."""

from __future__ import annotations

import json

import pytest

from rosy.world.state.projections.map_pose import MapPose
from fleet.server.sitemap.site_map_store import SiteMapError, SiteMapStore
from fleet.server.trip_geometry import SiteFrameMismatch, pose_view, robot_frame_goal
from test_trip_runner import BOTH, _arc, _free_map, _plan, _setup, _ticks, run
from test_trip_robot_frame_goal import _in_robot_map, _state


def _v2_map():
    """The same corridors, one place renamed: a valid body that must activate as a new version."""
    body = _free_map().body()
    body["places"][2]["name"] = "C2"
    from fleet.site_map import SiteMap
    return SiteMap.model_validate(body)


# ---- the active map row is verified on every read -----------------------------------------


def test_a_tampered_active_body_is_refused(tmp_path):
    path = tmp_path / "site-maps.sqlite3"
    store = SiteMapStore(path)
    version = store.import_if_empty(_free_map(), source="test")
    assert version == 1 and store.active() is not None

    with store._db:  # a row edited outside Fleet keeps its old sha256
        body = json.loads(store._active_row()[1])
        body["places"][2]["x"] = 9.9
        store._db.execute("UPDATE site_map_versions SET body = ? WHERE version = 1",
                          (json.dumps(body),))
    store.close()

    reopened = SiteMapStore(path)
    try:
        assert reopened.active() is None           # fail closed: no active map is served
        with pytest.raises(SiteMapError) as err:
            reopened.active_view()
        assert err.value.code == "SITE_MAP_BODY_HASH_MISMATCH"
        # D-1010 review: the first import must not die on the tampered row (startup survives) and
        # must not overwrite it either — the site stays without an active map, refused with 422.
        assert reopened.import_if_empty(_free_map(), source="test") is None
        assert reopened.active() is None
    finally:
        reopened.close()


def test_a_healthy_active_body_still_serves(tmp_path):
    path = tmp_path / "site-maps.sqlite3"
    store = SiteMapStore(path)
    store.import_if_empty(_free_map(), source="test")
    try:
        assert store.active() is not None
        view = store.active_view()
        assert view["version"] == 1 and view["sha256"] and view["map"]["map_id"] == "site"
    finally:
        store.close()


# ---- the free goal conversion refuses a site pose from another frame ----------------------


def test_robot_frame_goal_refuses_a_site_pose_anchored_on_another_map():
    site = MapPose(0.1, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "world_261026")
    state = _state(_in_robot_map(0.1, 0.0, 0.0))
    with pytest.raises(SiteFrameMismatch):
        robot_frame_goal((0.3, 0.0, 0.0), site, state, "map_v2_fleet")
    with pytest.raises(SiteFrameMismatch):        # no anchor frame at all is not the active map
        robot_frame_goal((0.3, 0.0, 0.0),
                         MapPose(0.1, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1), state, "site")
    with pytest.raises(SiteFrameMismatch):        # a degraded site pose never converts a goal
        robot_frame_goal((0.3, 0.0, 0.0),
                         MapPose(0.1, 0.0, 0.0, "DEGRADED", "sighting", 0.0, 0.1, 0.1, "site"),
                         state, "site")
    assert robot_frame_goal((0.3, 0.0, 0.0), site, state, "world_261026") is not None


def test_a_robot_without_its_own_map_pose_is_still_no_conversion():
    site = MapPose(0.1, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site")
    assert robot_frame_goal((0.3, 0.0, 0.0), site, _state((5.0, 5.0, 1.0), frame="odom"),
                            "site") is None


def test_the_robots_own_map_equal_to_the_site_map_proves_one_frame():
    """D-1010 review: the charge-return fallback, allowed only on this proof — the robot's
    reported map id is the active site map's, so site coordinates are its own frame."""
    site = MapPose(0.1, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "site")
    same = _state((5.0, 5.0, 1.0), frame="odom", map_id="site")
    assert robot_frame_goal((0.3, 0.0, 0.0), site, same, "site") == (0.3, 0.0, 0.0)
    other = _state((5.0, 5.0, 1.0), frame="odom", map_id="slam")
    assert robot_frame_goal((0.3, 0.0, 0.0), site, other, "site") is None


# ---- the trip sends no goal on another map version or frame --------------------------------


def test_a_free_trip_stops_when_the_active_map_is_not_the_plans_version():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    view = store.save_draft(_v2_map(), expected_revision=None, principal_id="kim")
    store.activate(expected_revision=view["revision"], principal_id="kim", route_active=False)
    assert store.active()[0] == 2                 # the plan is still on version 1

    _ticks(runner, ports)

    row = runner.view("p1")
    assert ports.goals == [] and row["state"] == "stopped" and row["reason"] == "map_version"
    assert row["detail"]["active_version"] == 2 and row["detail"]["map_version"] == 1


def test_a_free_trip_stops_when_the_site_pose_is_on_another_frame():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    ports.map_id = "site"

    async def robot_state(robot_id):
        return _state(_in_robot_map(ports.pose.x, ports.pose.y, ports.pose.yaw))

    runner._robot_state = robot_state
    _plan(store, ports, "ab:fwd", 0.1, "C")
    arc = _arc(store, "ab:fwd")
    x, y, yaw = arc.point_at(0.1)
    ports.pose = MapPose(x, y, yaw, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, "world_261026")
    run(runner.start("p1", "bob"))

    _ticks(runner, ports)

    row = runner.view("p1")
    assert ports.goals == [] and row["state"] == "stopped" and row["reason"] == "map_frame"
    assert row["detail"]["pose_map_id"] == "world_261026" and row["detail"]["map_id"] == "site"


def test_a_converted_goal_records_both_frames():
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    ports.map_id = "site"

    async def robot_state(robot_id):
        return _state(_in_robot_map(ports.pose.x, ports.pose.y, ports.pose.yaw), map_id="slam")

    runner._robot_state = robot_state
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))

    _ticks(runner, ports)

    assert ports.goals == [(2.0, 4.0)]
    frame = runner.view("p1")["detail"]["goal_frame"]
    assert frame == {"map_id": "site", "map_version": store.active()[0],
                     "robot_map_id": "slam", "goal_frame": "robot"}


def test_a_free_trip_stops_when_the_robots_map_differs_and_cannot_convert():
    """D-1010 review: not LOCALIZED and the robot's map id is not the site's — no conversion and
    no proof, so the site goal never goes out raw (review 2026-11-10, medium finding 1)."""
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    ports.map_id = "site"

    async def robot_state(robot_id):
        return _state((5.0, 5.0, 1.0), frame="odom", map_id="slam")

    runner._robot_state = robot_state
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))

    _ticks(runner, ports)

    row = runner.view("p1")
    assert ports.goals == [] and row["state"] == "stopped" and row["reason"] == "map_frame"
    assert row["detail"]["map_id"] == "site" and row["detail"]["robot_map_id"] == "slam"


def test_a_free_trip_stops_when_the_robot_state_is_unknown():
    """The state read itself answers nothing: no proof, no goal (fail closed)."""
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    ports.map_id = "site"

    async def robot_state(robot_id):
        return None

    runner._robot_state = robot_state
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))

    _ticks(runner, ports)

    row = runner.view("p1")
    assert ports.goals == [] and row["state"] == "stopped" and row["reason"] == "map_frame"
    assert row["detail"]["map_id"] == "site" and row["detail"]["robot_map_id"] is None


def test_a_free_trip_stops_when_a_snapshot_less_port_proves_no_frame():
    """A port without robot snapshots (D-1003 6) that does not declare its one frame either."""
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    runner._poses_in_robot_frame = False
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))

    _ticks(runner, ports)

    row = runner.view("p1")
    assert ports.goals == [] and row["state"] == "stopped" and row["reason"] == "map_frame"


def test_a_robot_on_the_site_map_gets_the_site_goal_even_unlocalized():
    """The charge-return case: no map pose to convert with, but the robot's reported map id
    proves its frame is the site map — the goal goes out unchanged and the audit says so."""
    runner, store, ports = _setup(_free_map(), caps=BOTH)
    ports.map_id = "site"

    async def robot_state(robot_id):
        return _state((5.0, 5.0, 1.0), frame="odom", map_id="site")

    runner._robot_state = robot_state
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))

    _ticks(runner, ports)

    assert ports.goals == [(1.0, 0.0)]
    frame = runner.view("p1")["detail"]["goal_frame"]
    assert frame == {"map_id": "site", "map_version": store.active()[0],
                     "robot_map_id": "site", "goal_frame": "site"}


def test_pose_view_carries_the_map_id():
    view = pose_view(MapPose(1.0, 2.0, 0.5, "LOCALIZED", "sighting", 0.0, 0.1, 0.2, "world_261026"))
    assert view["map_id"] == "world_261026"
    assert pose_view(None) is None
