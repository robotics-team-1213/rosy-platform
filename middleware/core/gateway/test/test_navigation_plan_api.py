"""A bound preview stays passive and only its exact path can enter the planned execution."""

from types import SimpleNamespace

import pytest

from core_api_web.api.command_activity import command_source
from test_api import OPERATOR, client  # noqa: F401
from test_core_trip_lease import FLEET, VIEWER, _open, robot  # noqa: F401
from test_map_snapshots import GRID


@pytest.mark.parametrize("change", [None, "grid", "same_grid_reload", "pose", "mode", "attempt", "cancel",
                                   "controller", "controller_after_mode", "mode_listener"])
def test_bound_plan_checks_live_scope_before_motion(client, monkeypatch, change):
    tc, svc = client
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)
    svc.state.set_map_id("s3-map", "occupancy:approved")
    svc.state.set_pose(0.0, 0.0, 0.0)
    svc.maps.set_map(GRID, map_id="s3-map")

    def waypoint(x, y):
        return SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=x, y=y)))

    path = SimpleNamespace(poses=[waypoint(0, 0), waypoint(0.2, 0.1), waypoint(0.5, 0)])
    sent = []
    svc.nav.executor = SimpleNamespace(
        compute_navigation_path=lambda *args, **kwargs: path,
        send_native_path=lambda route, run_id, **kw: sent.append((route, str(run_id), kw)),
        native_transport_snapshot=lambda: (0, False, False),
        path_controller_ready=lambda: True,
        cancel_goal=lambda: None,
    )
    body = {"x": 0.5, "y": 0.0, "yaw": 0.0, "expected_map_grid_id": "occupancy:approved",
            "correlation_id": "s3-attempt"}
    response = tc.post("/api/v1/navigation/bound-plan", json=body, headers=OPERATOR)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["points"] == [[0, 0], [0.2, 0.1], [0.5, 0]]
    assert plan["frame"] == "map" and plan["map_grid_id"] == "occupancy:approved"
    assert command_source("POST", "/api/v1/navigation/bound-plan") is None
    assert svc.modes.mode.value == "IDLE" and not sent

    if change == "grid":
        svc.state.set_map_id("s3-map", "occupancy:changed")
    elif change == "same_grid_reload":
        svc.state.invalidate_map_grid()
        svc.state.set_map_id("s3-map", "occupancy:approved")
    elif change == "pose":
        svc.state.set_pose(0.20, 0.0, 0.0)
    elif change == "mode":
        mode = type(svc.modes.mode)
        assert svc.modes.transition(mode.NAVIGATION)[0]
        assert svc.modes.transition(mode.IDLE)[0]
    elif change == "attempt":
        body["correlation_id"] = "another-attempt"
    elif change == "cancel":
        svc.nav.cancel()
    elif change == "controller":
        svc.nav.executor.path_controller_ready = lambda: False
    elif change == "controller_after_mode":
        svc.nav.executor.path_controller_ready = lambda: svc.modes.mode.value == "IDLE"
    elif change == "mode_listener":
        mode = type(svc.modes.mode)

        def stop_on_entry(_old, new):
            if new is mode.NAVIGATION:
                svc.modes.transition(mode.IDLE)

        svc.modes.change_listeners.append(stop_on_entry)

    response = tc.post("/api/v1/navigation/bound-goal", json={**body, "plan_id": plan["plan_id"]}, headers=OPERATOR)
    if change is not None:
        assert response.status_code == (503 if change.startswith("controller") else 409), response.text
        assert response.json()["error"]["detail"] == {"plan_id": plan["plan_id"], "native_admitted": False}
        assert not sent and svc.modes.mode.value == "IDLE"
        assert svc.state.snapshot().mode.value == "IDLE"
        return
    assert response.status_code == 200, response.text
    [(accepted_path, run_id, kwargs)] = sent
    assert accepted_path == path and accepted_path is not path
    assert response.json()["operation"]["run_id"] == run_id
    assert kwargs["correlation_id"] == body["correlation_id"]


@pytest.mark.parametrize("controller_ready", [False, True])
def test_planned_handoff_keeps_lane_stop_until_controller_admission(robot, controller_ready):
    tc, svc, _ = robot
    assert _open(tc).status_code == 200
    assert tc.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"}, headers=FLEET).status_code == 200
    line = svc.line_follow
    line._junction_seq = 12
    line._junction = {"seq": 12, "place_id": "S3_entry", "action": "stop", "state": "executing", "held": True}
    line._status = line._status.model_copy(update={"state": "HOLD", "reason": "junction_stop"})
    svc.state.set_map_id("s3-map", "occupancy:approved")
    svc.state.set_pose(0.0, 0.0, 0.0)
    svc.maps.set_map(GRID, map_id="s3-map")
    sent = []
    path = SimpleNamespace(poses=[SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=0.0, y=0.0)))])
    backend = svc.nav.executor
    backend.compute_navigation_path = lambda *args, **kwargs: path
    backend.send_native_path = lambda route, run_id, **kw: sent.append((route, str(run_id), line.active))
    backend.path_controller_ready = lambda: controller_ready
    backend.native_transport_snapshot = lambda: (0, False, False)

    body = {"x": 0.5, "y": 0.0, "expected_map_grid_id": "occupancy:approved", "correlation_id": "s3-attempt"}
    stop = {"lease_id": "lease-1", "trip_id": "trip-7", "junction_seq": 12, "stop_place_id": "S3_entry"}
    response = tc.post("/api/v1/navigation/bound-plan", json={**body, "line_stop": stop}, headers=FLEET)
    assert response.status_code == 200, response.text
    assert line.active and not sent
    owner = tc.get("/api/v1/navigation/state", headers=VIEWER).json()["owner"]
    response = tc.post("/api/v1/navigation/line-handoff-goal", headers=FLEET, json={
        **body, **stop, "plan_id": response.json()["plan_id"], "expected_boot_id": owner["boot_id"],
        "expected_owner_generation": owner["owner_generation"],
    })
    if controller_ready:
        assert response.status_code == 200, response.text
        assert sent == [(path, response.json()["operation"]["run_id"], False)]
    else:
        assert response.status_code == 503, response.text
        assert line.active and line.status().state == "HOLD" and not sent
