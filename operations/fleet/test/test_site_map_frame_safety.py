"""D-1010: a site map frame is never mixed into another — the active body is verified against
its stored sha256, a free goal is bound to the plan's map version and to both frames of the
conversion, and the frames of a sent goal are recorded for the audit."""

from __future__ import annotations

import json

import pytest

from rosy.world.state.projections.map_pose import MapPose
from fleet.server.site_map_store import SiteMapError, SiteMapStore
from fleet.server.trip_geometry import SiteFrameMismatch, pose_view, robot_frame_goal
from test_trip_runner import BOTH, _arc, _free_map, _plan, _setup, _ticks, run
from test_trip_robot_frame_goal import _in_robot_map, _state


#: Arc bc:fwd ends at stop place C (1, 1) heading +y; a plain stop place is a stop line, so the goal is the line
#: minus the registered body front and STOP_MARGIN_M (05e94ec043). Precision stops keep their commissioned pose.
_STOP_LINE_XY = (1.0, 1.0 - 0.0521)

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


@pytest.mark.parametrize("axis,value", [("x", 1.01), ("y", 0.99), ("yaw", 1.58)])
def test_measured_stop_limits_cannot_be_carried_with_an_edited_target(axis, value):
    from pydantic import ValidationError
    from fleet.site_map import SitePlace

    target = dict(id="S3", name="Unload", x=1., y=1., yaw=1.57, kind="stop")
    limits = dict(evidence_ref="field:S3", reference_pose=[1., 1., 1.57], longitudinal_m=.02,
                  lateral_m=.02, heading_rad=.05, position_uncertainty_m=.002,
                  heading_uncertainty_rad=.01, max_correction_m=.08)

    place = SitePlace.model_validate({**target, "precision_stop": limits})
    assert place.model_dump(mode="json")["precision_stop"]["reference_pose"] == [1., 1., 1.57]
    edited = {**target, axis: value}
    with pytest.raises(ValidationError, match="must match this place"):
        SitePlace.model_validate({**edited, "precision_stop": limits})
    assert SitePlace.model_validate(edited).precision_stop is None


def test_pose_view_carries_the_map_id():
    view = pose_view(MapPose(1.0, 2.0, 0.5, "LOCALIZED", "sighting", 0.0, 0.1, 0.2, "world_261026"))
    assert view["map_id"] == "world_261026"
    assert pose_view(None) is None


# D-1022: with fleet.trip.map_binding_required the approved binding of the loaded grid is the only proof.
_TRUTH = __import__("fleet.localization.map_binding", fromlist=["Fit"]).Fit(0.4, 0.3, -0.2, ())
_GRID = "occupancy:0123456789ab"
_SPAN = [(-1.0, -0.5), (1.0, -0.5), (0.9, 0.45)]


def _bound_setup(map_id="slam", grid=_GRID, approve=True, store_out=None, state_out=None, named_setup=None,
                 mixed=False, precision=None, binding_required=True, terminal_mode="free"):
    site = _free_map()
    if mixed:
        site.edges[0] = site.edges[0].model_copy(update={"drive_mode": "lane"})
    if named_setup is not None:
        site.edges[1] = site.edges[1].model_copy(update={"drive_mode": terminal_mode})
        site = site.model_copy(update={"places": [p.model_copy(update={"kind": "stop", "yaw": 1.570796, "precision_stop": precision}) if p.id == "C" else p
                                                  for p in site.places]})
    runner, store, ports = _setup(site, caps=BOTH, map_binding_required=binding_required)
    if store_out is not None:
        store_out.append(store)
    ports.map_id = "site"
    state = {**_state((0.0, 0.0, 0.0), map_id=map_id), "map_grid_id": grid,
             "navigation": "ARRIVED", "mode": "NAVIGATION", "line_follow": {"mode": "OFF"},
             "velocity": {"linear": 0.0, "angular": 0.0}}
    if state_out is not None:
        state_out.append(state)

    async def robot_state(robot_id):
        if precision is None:
            return state
        from datetime import datetime, timezone

        pose = ports.pose
        x, y = _TRUTH.inverse((pose.x, pose.y))
        observed = datetime.fromtimestamp(ports.now - .01, timezone.utc).isoformat()
        snapshot = {"pose": {"x": x, "y": y, "yaw": pose.yaw - _TRUTH.yaw}, "pose_frame": "map",
                    "odom_pose": {"x": x, "y": y, "yaw": pose.yaw, "stamp": ports.now - .01}}
        sample = {"evidence": "fresh", "received_at": observed}
        overrides = state if "pose_frame" in state else {k: v for k, v in state.items() if k != "pose"}
        merged = {**snapshot, **overrides}
        existing = merged.get("evidence") or {}
        merged["evidence"] = {**existing, "pose": {**sample, **existing.get("pose", {})}}
        return merged

    runner._robot_state = robot_state
    if approve:
        pairs = [{"site": list(p), "robot": list(_TRUTH.inverse(p))} for p in _SPAN]
        store.map_bindings.approve("rosy_60", {**state, "map_grid_id": _GRID},
                                   (store.active()[1].map_id, store.active()[0]), pairs,
                                   [{"site": [0.0, 0.0], "robot": list(_TRUTH.inverse((0.0, 0.0)))}], "bob")
    if named_setup is not None:
        named_setup(runner, ports)
    if mixed:
        _plan(store, ports, "ab:fwd", 0.8, "C")
    else:
        _plan(store, ports, "bc:fwd" if named_setup is not None else "ab:fwd", 0.1, "C")
    if precision is not None and (terminal_mode != "free" or not approve):
        from fleet.server.trip_ports import TripError

        with pytest.raises(TripError) as refused:
            run(runner.start("p1", "bob"))
        expected = "PRECISION_STOP_REQUIRES_NAV2_TERMINAL" if terminal_mode != "free" else "TRIP_POSE_UNTRUSTED"
        assert refused.value.code == expected
        assert not ports.line_starts
    else:
        run(runner.start("p1", "bob"))
        _ticks(runner, ports)
    return runner, ports


@pytest.mark.parametrize("condition", ["valid", "new_binding", "old_tf", "future_tf", "odom_pose",
                                       "wrong_grid", "no_fit", "revoke_at_lease", "revoke_at_line_send", "move_at_lease"])
def test_commissioned_trip_plans_from_the_bound_slam_pose(condition):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fleet.server.site_auth import SitePrincipal
    from fleet.server.trip_routes import install_trip_routes
    from fleet.site_map import SiteMap
    from fleet.swarm.dispatch_guard import check_dispatch

    site = _free_map().body()
    mixed = condition in ("revoke_at_lease", "revoke_at_line_send", "move_at_lease")
    if mixed:
        site["edges"][0]["drive_mode"] = "lane"
    target = next(place for place in site["places"] if place["id"] == "C")
    target.update(kind="stop", yaw=1.570796, precision_stop=dict(
        evidence_ref="bench", reference_pose=[1., 1., 1.570796], longitudinal_m=.02,
        lateral_m=.02, heading_rad=.05, position_uncertainty_m=.002,
        heading_uncertainty_rad=.01, max_correction_m=.08))
    runner, store, ports = _setup(SiteMap.model_validate(site), caps=BOTH)
    x, y = _TRUTH.inverse((.6, 0.) if mixed else (1., .1))
    pose = dict(x=x, y=y, yaw=(0. if mixed else 1.570796) - _TRUTH.yaw)
    age = {"old_tf": 2.1, "future_tf": -.1}.get(condition, .01)
    stamp = datetime.fromtimestamp(ports.now - age, timezone.utc).isoformat()
    state = {**_state((x, y, pose["yaw"]), map_id="slam"), "map_grid_id": _GRID,
             "pose_frame": "odom" if condition == "odom_pose" else "map",
             "odom_pose": {**pose, "stamp": ports.now - .01},
             "evidence": {"pose": {"evidence": "fresh", "received_at": stamp}}}

    async def robot_state(_robot_id):
        return state

    runner.named_stop_state = robot_state

    def approve():
        return store.map_bindings.approve("rosy_60", state, ("site", store.active()[0]),
            [{"site": list(p), "robot": list(_TRUTH.inverse(p))} for p in _SPAN],
            [{"site": [0., 0.], "robot": list(_TRUTH.inverse((0., 0.)))}], "bob")

    approval = approve() if condition != "no_fit" else None
    if condition == "wrong_grid":
        state["map_grid_id"] = "occupancy:fedcba987654"

    def operator():
        return SitePrincipal(principal_id="bob", role="operator")

    async def caps_for(robot_id):
        return ports.caps_for(robot_id)

    app = FastAPI()
    console = SimpleNamespace(robot_ids={"rosy_60"})
    install_trip_routes(app, console=console, site_maps=store, routing_config=store.routing_config,
                        require_operator=operator, require_named_operator=operator,
                        caps_for=caps_for, runner=runner, read_guard=[])
    client = TestClient(app)
    response = client.post("/api/fleet/robots/rosy_60/trip", json={"to": "C"})
    if not mixed and condition not in ("valid", "new_binding"):
        assert response.status_code == 409
        assert response.json()["detail"]["detail"] == {"reason": "APPROVED_SLAM_POSE_REQUIRED"}
        assert not ports.goals and not ports.line_starts
        return
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["precision_binding_id"] == approval["binding_id"]
    assert plan["segments"][0]["edge_id"] == ("ab" if mixed else "bc")
    assert plan["segments"][0]["s_from"] == pytest.approx(.6 if mixed else .1)
    if condition == "new_binding":
        assert approve()["binding_id"] != approval["binding_id"]
    if mixed:
        ports.core.mode = "OFF"

        async def revoke_during_lease(*_args, **_kwargs):
            assert store.map_bindings.revoke("rosy_60", "operator")

        async def revoke_before_wire_send(_robot_id):
            assert store.map_bindings.revoke("rosy_60", "operator")
            check_dispatch(path="/api/v1/line-follow/mode")
            ports.line_starts.append(_robot_id)

        async def move_during_lease(*_args, **_kwargs):
            px, py = _TRUTH.inverse((.6, .4))
            state["pose"].update(x=px, y=py)

        if condition == "revoke_at_lease":
            runner.lease.open = revoke_during_lease
        elif condition == "move_at_lease":
            runner.lease.open = move_during_lease
        else:
            ports.start_camera_line = revoke_before_wire_send
    response = client.post(f"/api/fleet/trips/{plan['plan_id']}/start")
    if condition == "new_binding":
        assert response.status_code == 422 and response.json()["detail"]["code"] == "TRIP_POSE_UNTRUSTED"
        assert not ports.goals and not ports.line_starts
    elif mixed:
        assert response.status_code == 409, response.text
        assert not ports.goals and not ports.line_starts
    else:
        assert response.status_code == 200, response.text
        assert response.json()["detail"]["precision_binding_id"] == approval["binding_id"]


@pytest.mark.parametrize("case", ["arrived", "changed_grid", "replacement_run",
                                  "precision_ok", "precision_forward", "precision_reverse", "precision_lateral",
                                  "precision_heading", "precision_stale", "precision_pose_frame_mismatch",
                                  "precision_after_repark", "precision_lane_terminal", "precision_no_binding"])
def test_named_free_stop_waits_for_the_sent_nav2_run_and_transport_release(case):
    from uuid import uuid4

    identity = {"boot_id": str(uuid4()), "run_id": str(uuid4()), "kind": "navigate"}
    replies, calls, stores, states = {}, [], [], []

    def configure(runner, ports):
        async def send(robot_id, x, y, yaw, *, attempt_id, stop_binding):
            assert stop_binding["map_grid_id"] == _GRID
            identity["correlation_id"] = attempt_id
            calls.append((robot_id, yaw))
            return {"accepted": True, "operation": {**identity, "phase": "RUNNING"}}

        async def read(robot_id, run_id):
            assert (robot_id, run_id) == ("rosy_60", identity["run_id"])
            if replies.get("quiescence", {}).get("observed_at", "").endswith("+00:00"):
                if case == "changed_grid":
                    states[0]["map_grid_id"] = "occupancy:fedcba987654"
                elif case == "replacement_run":
                    states[0]["navigation"] = "PLANNING"
            return replies

        runner._goal, runner.navigation_readback = send, read

    from fleet.site_map import PrecisionStopLimits

    precision = PrecisionStopLimits(evidence_ref="bench-synthetic", reference_pose=(1., 1., 1.570796),
                                   longitudinal_m=.02, lateral_m=.02,
                                   heading_rad=.05, position_uncertainty_m=.002,
                                   heading_uncertainty_rad=.01, max_correction_m=.08) if case.startswith("precision_") else None
    runner, ports = _bound_setup(store_out=stores, state_out=states, named_setup=configure, precision=precision,
                                 binding_required=precision is None, approve=case != "precision_no_binding",
                                 terminal_mode="lane" if case == "precision_lane_terminal" else "free")
    if case in ("precision_lane_terminal", "precision_no_binding"):
        assert calls == [] and runner.running() is None
        return
    if precision is not None:
        site_xy = {"precision_ok": (1., 1.), "precision_forward": (1., .96),
                   "precision_reverse": (1., 1.04), "precision_lateral": (1.04, 1.)}.get(case, (1., 1.))
        robot_x, robot_y = _TRUTH.inverse(site_xy)
        states[0].update(pose={"x": robot_x, "y": robot_y, "yaw": 1.570796 - _TRUTH.yaw},
                         pose_frame="odom" if case == "precision_pose_frame_mismatch" else "map",
                         evidence={key: {"evidence": "fresh"} for key in ("pose", "velocity")})
        if case == "precision_heading":
            states[0]["pose"]["yaw"] += .08
        if case == "precision_stale":
            states[0]["evidence"]["pose"]["evidence"] = "stale"
        if case == "precision_after_repark":
            states[0]["mode"] = "IDLE"

            async def confirm(robot_id, operation, *, ready):
                assert robot_id == "rosy_60" and operation["run_id"] == identity["run_id"]
                assert ready(states[0]) is True
                return {"operation": {"kind": "repark", "result": "SUCCEEDED"}}

            runner.confirm_named_precision = confirm
    assert len(calls) == 1
    ports.at(stores[0].active()[2].arcs["bc:fwd"], 0.95)
    _ticks(runner, ports)
    if case in ("precision_stale", "precision_pose_frame_mismatch"):
        view = runner.view("p1")
        assert view["state"] == "stopped" and view["reason"] == "pose"
        assert "named_stop_completion" not in view["detail"]
        return
    assert runner.view("p1")["state"] == "running"

    operation = {**identity, "phase": "TERMINAL", "result": "SUCCEEDED"}
    owner = {"boot_id": identity["boot_id"], "owner_run_id": None, "owner_generation": 8}
    proof = {**owner, "requested_run_id": identity["run_id"], "quiescent": True,
             "transport_generation": 9, "admitting": False, "pending_submission": False,
             "actuating_callback": False, "lease_active": False}
    replies.update(lookup="FOUND", operation={**operation, "run_id": str(uuid4())},
                   owner=owner, quiescence=proof)
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running"
    replies.update(operation=operation, quiescence={**proof, "lease_active": True})
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running"
    replies["quiescence"] = {**proof, "observed_at": "2026-11-20T09:00:00"}
    _ticks(runner, ports)
    assert runner.view("p1")["state"] == "running"
    replies["quiescence"] = {**proof, "observed_at": "2026-11-20T00:00:00+00:00"}
    _ticks(runner, ports)
    view = runner.view("p1")
    if case == "replacement_run":
        assert view["state"] == "running" and len(calls) == 1
        assert "named_stop_completion" not in view["detail"]
        return
    if case == "changed_grid":
        assert view["state"] == "failed" and len(calls) == 1
        assert view["detail"]["goal_reason"] == "NAMED_STOP_DISPATCH_FRAME_CHANGED"
        assert "named_stop_completion" not in view["detail"]
        return
    if precision is not None:
        decision = view["detail"]["named_stop_precision"]
        if case not in ("precision_ok", "precision_after_repark"):
            assert view["state"] == "running" and "named_stop_completion" not in view["detail"]
            if case == "precision_lateral":
                assert decision["decision"] == "HOLD" and decision["reason"] == "lateral_outside_limits"
            elif case == "precision_heading":
                assert decision["decision"] == "HOLD" and decision["reason"] == "heading_outside_limits"
            elif case == "precision_stale":
                assert decision["decision"] == "WAIT"
            elif case == "precision_pose_frame_mismatch":
                assert decision == {"decision": "WAIT", "reason": "map_pose_required"}
            else:
                assert decision["decision"] == "REPARK"
                assert decision["forward_m"] == pytest.approx(.04 if case == "precision_forward" else -.04)
            return
        assert decision["decision"] == "IN_TOLERANCE"
        if case == "precision_after_repark":
            assert view["detail"]["named_stop_repark_completion"]["operation"]["kind"] == "repark"
    assert view["state"] == "arrived" and len(calls) == 1
    completion = view["detail"]["named_stop_completion"]
    assert completion["operation"] == operation
    assert completion["owner"] == owner and completion["quiescence"] == replies["quiescence"]
    dispatch = completion["dispatch"]
    assert dispatch["attempt_id"] == operation["correlation_id"]
    assert dispatch["robot_id"] == "rosy_60" and dispatch["place"] == "C"
    assert dispatch["map_sha256"] == stores[0].active_view()["sha256"]
    assert dispatch["binding_id"] == stores[0].map_bindings.active("rosy_60")["binding_id"]
    assert dispatch["map_grid_id"] == _GRID
    # A commissioned precision stop is its measured pose; a plain stop place is a stop line (body front on it).
    want = (1.0, 1.0) if precision is not None else _STOP_LINE_XY
    assert dispatch["site_target"] == pytest.approx({"x": want[0], "y": want[1], "yaw": 1.570796}, abs=1e-3)
    assert (dispatch["robot_target"]["x"], dispatch["robot_target"]["y"]) == pytest.approx(_TRUTH.inverse(want), abs=1e-3)


@pytest.mark.parametrize("case", ["complete", "lost_reply"])
def test_mixed_named_stop_waits_for_the_live_hold_and_sends_only_the_scoped_goal(case):
    from uuid import uuid4

    ident = {"boot_id": str(uuid4()), "run_id": str(uuid4()), "kind": "navigate"}
    requests, stores, state = [], [], []
    readback, held = {}, False

    def configure(runner, ports):
        async def junction(robot_id):
            observed = ports.core.status()
            return {**observed, "line_stop_held": held, "active_trip_lease_id": "lease-a"}

        async def send(robot_id, x, y, yaw, *, attempt_id, stop_binding, line_handoff):
            scope, ready = line_handoff
            assert ready()
            assert scope == dict(lease_id="lease-a", trip_id="p1", job_id=None,
                                 junction_seq=1, stop_place_id="B", staging_xy=[1.0, 0.0],
                                 staging_radius_m=runner.config.arrive_lane_m,
                                 terminal={"arc_id": "bc:fwd", "s_from": 0.0, "s_to": pytest.approx(_STOP_LINE_XY[1], abs=1e-3),
                                           "robot_kind": runner._live[robot_id].view["caps"]["kind"]})
            assert stop_binding["map_grid_id"] == _GRID
            assert (x, y) == pytest.approx(_TRUTH.inverse(_STOP_LINE_XY), abs=1e-3)
            ident["correlation_id"] = attempt_id
            requests.append(scope)
            if case == "lost_reply":
                raise OSError("handoff outcome unknown")
            return {"accepted": True, "operation": {**ident, "phase": "RUNNING"}}

        async def read(robot_id, run_id):
            assert (robot_id, run_id) == ("rosy_60", ident["run_id"])
            return readback

        runner._goal, runner.navigation_readback = send, read
        ports.junction_state = junction

    runner, ports = _bound_setup(store_out=stores, state_out=state, named_setup=configure, mixed=True)
    live = runner._live["rosy_60"]
    live.view["lease"] = {"state": "held", "lease_id": "lease-a", "renewed_at": runner.lease.now()}
    assert ports.sent[0][:2] == ("stop", "B")
    ports.at(_arc(stores[0], "bc:fwd"), 0.05)
    _ticks(runner, ports)
    assert requests == [] and live.view["segment_index"] == 0

    held = True
    _ticks(runner, ports)
    assert len(requests) == 1, live.view
    if case == "lost_reply":
        assert live.view["state"] == "failed"
        assert ports.canceled == ["rosy_60"] and ports.held == ["rosy_60"]
        assert runner.robot_busy("rosy_60")
        assert stores[0].pending_handoff_stops()[0]["detail"]["named_stop_handoff_pending"] == {
            **requests[0], "correlation_id": ident["correlation_id"]}
        _ticks(runner, ports)
        assert len(requests) == 1
        return

    assert live.view["segment_index"] == 1
    ports.at(_arc(stores[0], "bc:fwd"), 0.96)
    _ticks(runner, ports)
    assert live.view["state"] == "running"
    owner = {"boot_id": ident["boot_id"], "owner_run_id": None, "owner_generation": 8}
    readback.update(lookup="FOUND", operation={**ident, "phase": "TERMINAL", "result": "SUCCEEDED"},
                    owner=owner, quiescence={**owner, "requested_run_id": ident["run_id"],
                    "quiescent": True, "transport_generation": 9, "admitting": False,
                    "pending_submission": False, "actuating_callback": False, "lease_active": False,
                    "observed_at": "2026-11-20T00:00:00+00:00"})
    _ticks(runner, ports)
    assert live.view["state"] == "arrived" and len(requests) == 1


def test_failed_handoff_remains_fenced_after_restart_until_the_exact_stop_is_proved(tmp_path):
    from datetime import datetime, timezone
    from uuid import uuid4
    from fleet.server.handoff_recovery import stopped_handoff

    path = tmp_path / "site.db"
    _, first, _ = _setup(_free_map(), path=path)
    scope = {"lease_id": "lease-a", "trip_id": "trip-a", "job_id": None, "junction_seq": 1,
             "stop_place_id": "B", "correlation_id": "attempt-a"}
    failed = {"trip_id": "trip-a", "robot_id": "rosy_60", "state": "failed",
              "detail": {"named_stop_handoff_pending": scope, "stop_sent": False}}
    first.put_trip(failed)
    runner, persisted, ports = _setup(_free_map(), path=path)
    assert runner.robot_busy("rosy_60")
    assert persisted.trip("trip-a") == failed

    owner = {"boot_id": str(uuid4()), "owner_run_id": None, "owner_generation": 8}
    operation = {"boot_id": owner["boot_id"], "run_id": str(uuid4()), "kind": "navigate",
                 "phase": "TERMINAL", "result": "CANCELED", "reason": "CANCELED", "correlation_id": "other"}
    view = {"owner": owner, "operation": operation, "lookup": "FOUND", "navigation": "CANCELED",
            "quiescence": {**owner, "requested_run_id": operation["run_id"],
                           "observed_at": datetime.now(timezone.utc).isoformat(),
                           "quiescent": True, "transport_generation": 9, "admitting": False,
                           "pending_submission": False, "actuating_callback": False, "lease_active": False}}

    class Core:
        async def _get(self, path):
            assert path == "/api/v1/navigation/state"
            return view

        async def state(self):
            return {"mode": "NAVIGATION", "velocity": {"linear": 0.0, "angular": 0.0},
                    "line_follow": {"mode": "OFF"}, "trip_lease": {"lease_id": "lease-a"}}

    async def reconcile(robot_id, recorded_scope, accepted):
        assert robot_id == "rosy_60" and recorded_scope == scope and accepted is None
        return await stopped_handoff(Core(), recorded_scope, accepted)

    runner.halts.reconcile_handoff = reconcile
    _ticks(runner, ports)
    assert runner.robot_busy("rosy_60")
    operation["correlation_id"] = "attempt-a"
    view["quiescence"]["actuating_callback"] = True
    _ticks(runner, ports)
    assert runner.robot_busy("rosy_60")
    view["quiescence"]["actuating_callback"] = False
    _ticks(runner, ports)
    assert not runner.robot_busy("rosy_60")
    assert persisted.trip("trip-a")["detail"]["named_stop_handoff_stop_verified"]
    assert not persisted.pending_handoff_stops()


@pytest.mark.parametrize("case", ["accepted_only", "wrong_seq", "wrong_lease", "traffic",
                                 "estop", "nonzero", "held"])
def test_named_lane_stop_requires_its_own_live_stop_hold(case):
    from types import SimpleNamespace

    from fleet.server.trip_ports import HttpLaneJunction
    from fleet.server.trip_steps import TripSteps

    async def read(robot_id, after):
        assert (robot_id, after) == ("rosy_60", 17)
        return {"safety": {"estop": case == "estop"},
                "trip_lease": {"lease_id": "previous" if case == "wrong_lease" else "lease-a"},
                "line_follow": {
                    "state": "TRACKING" if case == "accepted_only" else "HOLD",
                    "reason": "junction_stop", "linear": 0.1 if case == "nonzero" else 0.0, "angular": 0.0,
                    "junction": {"seq": 11 if case == "wrong_seq" else 12, "place_id": "S3",
                                 "state": "executing", "pending_action": "stop"},
                }}

    steps = TripSteps()
    steps.traffic = SimpleNamespace(holds=lambda *_: case == "traffic")
    port = HttpLaneJunction(lambda: {}, read=read)
    live = SimpleNamespace(
        sent={"index": 0, "seq": 12, "action": "stop", "place": "S3"},
        view={"detail": {}, "lease": {"state": "held", "lease_id": "lease-a"}},
        junction=run(port.junction_state("rosy_60", after=17)))
    expected = case == "held"
    assert steps._confirm_lane_stop(live, 0) is expected
    assert ("named_stop_lane_hold" in live.view["detail"]) is expected


def test_a_bound_robot_gets_the_goal_through_its_binding_even_on_an_equal_map_id():
    for map_id in ("slam", "site"):  # the map_id shortcut no longer proves one frame
        runner, ports = _bound_setup(map_id)
        assert ports.goals == [pytest.approx(_TRUTH.inverse((1.0, 0.0)), abs=1e-3)]  # the port rounds to mm
        assert runner.view("p1")["detail"]["goal_frame"]["map_grid_id"] == _GRID


@pytest.mark.parametrize("kw, reason", [({"approve": False}, "MAP_BINDING_REQUIRED"),
                                        ({"grid": "occupancy:ffffffffffff"}, "MAP_BINDING_GRID_CHANGED")])
def test_a_required_binding_that_does_not_match_stops_the_trip(kw, reason):
    runner, ports = _bound_setup(**kw)
    row = runner.view("p1")
    assert ports.goals == [] and row["reason"] == "map_frame" and row["detail"]["binding"] == reason


def test_robot_frame_goal_inverts_the_binding_and_refuses_without_one():
    site = MapPose(0.0, 0.0, 0.0, "LOCALIZED", "sighting", 0.0, 0.1, 0.1)
    x, y, yaw = robot_frame_goal((0.5, 0.2, 1.0), site, {}, "site", (_TRUTH, ""))
    assert _TRUTH.apply((x, y)) == pytest.approx((0.5, 0.2)) and yaw == pytest.approx(1.0 - 0.4)
    with pytest.raises(SiteFrameMismatch) as err:
        robot_frame_goal((0.5, 0.2, 1.0), site, {"map_id": "site"}, "site", (None, "MAP_BINDING_SITE_CHANGED"))
    assert err.value.reason == "MAP_BINDING_SITE_CHANGED"


def test_revoking_the_binding_under_a_running_goal_stops_and_cancels_it():
    stores = []
    runner, ports = _bound_setup(store_out=stores)
    assert len(ports.goals) == 1 and runner.view("p1")["state"] != "stopped"
    stores[0].map_bindings.revoke("rosy_60", "bob", "map re-saved")
    _ticks(runner, ports)
    row = runner.view("p1")
    assert row["reason"] == "map_frame" and row["detail"]["binding"] == "MAP_BINDING_REQUIRED"  # revoked: no active binding at all
    assert ports.canceled == ["rosy_60"] and len(ports.goals) == 1


def test_a_required_binding_stops_a_port_that_only_declares_one_frame():
    runner, store, ports = _setup(_free_map(), caps=BOTH, map_binding_required=True)
    runner._poses_in_robot_frame = True
    _plan(store, ports, "ab:fwd", 0.1, "C")
    run(runner.start("p1", "bob"))
    _ticks(runner, ports)
    row = runner.view("p1")
    assert ports.goals == [] and row["detail"]["binding"] == "MAP_BINDING_REQUIRED"


def test_a_robot_that_loads_another_grid_under_a_running_goal_is_stopped():
    states = []
    runner, ports = _bound_setup(state_out=states)
    assert len(ports.goals) == 1
    states[0]["map_grid_id"] = "occupancy:ffffffffffff"  # the robot re-saved or swapped its map mid-goal
    _ticks(runner, ports)
    row = runner.view("p1")
    assert row["detail"]["binding"] == "MAP_BINDING_GRID_CHANGED" and ports.canceled == ["rosy_60"]
