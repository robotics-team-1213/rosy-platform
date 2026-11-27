"""Tests for event-driven coupled simulation & boundary fault toggles (D-1088)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[1]
for rel in ("tools/sim", "applications/world"):
    entry = str(ROOT / rel)
    if entry not in sys.path:
        sys.path.insert(0, entry)

import coupled_sim_controller as csc  # noqa: E402
import world_state  # noqa: E402

MAP_SHA = "ab" * 32


def _controller(**kwargs) -> csc.CoupledSimController:
    return csc.CoupledSimController(site_map_sha256=MAP_SHA, **kwargs)


def test_happy_path_three_boundary_events_and_cell_stages() -> None:
    ctrl = _controller()
    s3 = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.012, dy_m=-0.008, dyaw_rad=0.035)
    assert s3["accepted"] is True and s3["cargo_state"] == "HANDOFF_AT_S3"
    assert s3["mujoco_intake_pose"] == {
        "dx_m": 0.012, "dy_m": -0.008, "dyaw_rad": 0.035, "cargo_id": "cargo-sim-01", "robot_id": "rosy_45",
    }

    lifted = ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)
    assert lifted["accepted"] is True and lifted["gazebo_tray_empty"] is True
    assert ctrl.pinky_has_cargo is False

    blocked_clear = ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=True)
    assert blocked_clear["accepted"] is False and blocked_clear["reason"] == "ARM_IN_BED_ZONE"

    clear = ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=False)
    assert clear["accepted"] is True and clear["pinky_departure_permitted"] is True

    assert ctrl.advance_cell_stage("ON_BELT")["cargo_state"] == "ON_BELT"
    assert ctrl.advance_cell_stage("IN_CELL_AB")["cargo_state"] == "IN_CELL_AB"
    shipped = ctrl.advance_cell_stage("ON_SHIP")
    assert shipped["accepted"] is True and shipped["cargo_state"] == "ON_SHIP"
    assert ctrl.inconclusive is False


def test_fail_closed_transitions_drop_fault_and_reset() -> None:
    ctrl = _controller()
    with pytest.raises(ValueError, match="INVALID_CARGO_TRANSITION"):
        ctrl.handle_cargo_lifted_or_dropped(lifted=True)

    assert ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)["accepted"]
    dropped = ctrl.handle_cargo_lifted_or_dropped(lifted=False, bilateral_lift=False)
    assert dropped["accepted"] is False and dropped["cargo_state"] == "CARGO_FAULT"
    assert dropped["hitl_required"] is True

    depart = ctrl.handle_cell_bed_clear(arm_in_bed_zone=False)
    assert depart["accepted"] is False and depart["pinky_departure_permitted"] is False
    assert depart["reason"] == "CARGO_FAULT_HOLD"

    snap = ctrl.reset(clear_faults=True)
    assert snap["cargo_state"] == "ON_PINKY" and snap["pinky_has_cargo"] is True and snap["events"] == []


def test_anti_faking_and_rtf_gate() -> None:
    with pytest.raises(ValueError, match="SIM_CANNOT_IMPERSONATE_REAL_SITE"):
        _controller(world_id="real-site")
    with pytest.raises(ValueError, match="INVALID_SIM_ADAPTER"):
        _controller(adapter="real")

    ctrl = _controller()
    res = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0, rtf=0.85)
    assert res["accepted"] is True and res["inconclusive"] is True
    assert ctrl.min_rtf == pytest.approx(0.85)


def test_four_field_fault_toggles_enable_refuse_and_recover() -> None:
    ctrl = _controller()
    with pytest.raises(ValueError, match="UNKNOWN_FAULT_ID"):
        ctrl.faults.enable("unknown.fault")

    # 1. pinky.s3_brake_unmeasured
    ctrl.faults.enable("pinky.s3_brake_unmeasured")
    refused = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)
    assert refused["accepted"] is False and refused["reason"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED"
    ctrl.faults.disable("pinky.s3_brake_unmeasured")

    # 2. arm.usb_unplugged (arm_s then arm_b)
    ctrl.faults.enable("arm.usb_unplugged", {"arm_id": "arm_s"})
    assert ctrl.faults.apply_arm_presence_boundary("arm_s", True) is False
    assert ctrl.faults.apply_arm_presence_boundary("arm_a", True) is True
    refused_arm = ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)
    assert refused_arm["accepted"] is False and refused_arm["reason"] == "ARM_USB_UNPLUGGED:arm_s"
    ctrl.faults.disable("arm.usb_unplugged")

    assert ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)["accepted"]
    assert ctrl.handle_cargo_lifted_or_dropped(lifted=True)["accepted"]

    # 3. pinky.tangled_or_stall
    ctrl.faults.enable("pinky.tangled_or_stall", {"robot_id": "rosy_45"})
    assert ctrl.faults.apply_pinky_motion_boundary("rosy_45", 0.15, 0.4) == (0.0, 0.0)
    assert ctrl.faults.apply_pinky_motion_boundary("rosy_42", 0.15, 0.4) == (0.15, 0.4)
    stalled = ctrl.handle_cell_bed_clear(arm_in_bed_zone=False)
    assert stalled["accepted"] is False and stalled["reason"] == "PINKY_TANGLED_OR_STALL"
    ctrl.faults.disable("pinky.tangled_or_stall")
    assert ctrl.handle_cell_bed_clear(arm_in_bed_zone=False)["pinky_departure_permitted"] is True

    # downstream arm_b unplug check
    assert ctrl.advance_cell_stage("ON_BELT")["accepted"]
    ctrl.faults.enable("arm.usb_unplugged", {"arm_id": "arm_b"})
    blocked_ab = ctrl.advance_cell_stage("IN_CELL_AB")
    assert blocked_ab["accepted"] is False and blocked_ab["reason"] == "ARM_USB_UNPLUGGED:arm_b"
    ctrl.faults.disable("arm.usb_unplugged")
    assert ctrl.advance_cell_stage("IN_CELL_AB")["accepted"] is True

    # 4. vision.calibration_mismatch (pure copy, non-mutating)
    raw_obs = {"source_id": "ceiling_north", "x_m": 1.0, "y_m": 2.0, "yaw_rad": 0.1, "score": 0.98}
    ctrl.faults.enable("vision.calibration_mismatch")
    bad_obs = ctrl.faults.apply_vision_boundary(raw_obs)
    assert raw_obs["score"] == 0.98 and raw_obs["x_m"] == 1.0
    assert bad_obs["score"] == pytest.approx(0.472) and bad_obs["calibration_mismatch_injected"] is True
    assert bad_obs["x_m"] == pytest.approx(1.18) and bad_obs["y_m"] == pytest.approx(1.88)
    ctrl.faults.disable("vision.calibration_mismatch")
    assert ctrl.faults.apply_vision_boundary(raw_obs)["score"] == 0.98


def test_world_projection_passes_read_only_parity() -> None:
    ctrl = _controller()
    ctrl.faults.enable("arm.usb_unplugged", {"arm_id": "arm_b"})
    snap = ctrl.build_world_state(now_ms=1_795_800_000_000)
    canonical = {
        "site_map_sha256": MAP_SHA,
        "fleet_robots": {"pinkys": ["rosy_42", "rosy_45", "rosy_46"], "arms": ["arm_s", "arm_a", "arm_b"]},
        "has_cargo_tray": True,
    }
    parity = world_state.verify_world_parity(canonical, snap)
    assert parity["ok"] is True, parity
    assert snap["read_only"] is True and snap["adapter"] == "gazebo" and snap["world_id"] == "coupled-sim"
    assert snap["arms_observed"] == {"arm_s": True, "arm_a": True, "arm_b": False}
    assert "arm.usb_unplugged" in snap["active_faults"]


def test_loopback_http_server_fault_and_event_roundtrip() -> None:
    ctrl = _controller()
    with pytest.raises(ValueError, match="REFUSING_NON_LOOPBACK_BIND"):
        csc.build_server(ctrl, host="0.0.0.0", port=0)

    server = csc.build_server(ctrl, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def req(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        r = urllib.request.Request(
            base + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urllib.request.urlopen(r, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read().decode("utf-8"))

    try:
        assert req("GET", "/healthz") == (200, {"status": "ok", "world_id": "coupled-sim"})
        code, _ = req("POST", "/api/sim/faults/pinky.s3_brake_unmeasured", {"enabled": True})
        assert code == 200
        _, r1 = req("POST", "/api/sim/events/s3-arrived", {"dx_m": 0.01, "dy_m": 0.0, "dyaw_rad": 0.0})
        assert r1["accepted"] is False and r1["reason"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED"

        assert req("POST", "/api/sim/faults/pinky.s3_brake_unmeasured", {"enabled": False})[0] == 200
        _, r2 = req("POST", "/api/sim/events/s3-arrived", {"dx_m": 0.01, "dy_m": 0.0, "dyaw_rad": 0.0})
        assert r2["accepted"] is True and r2["cargo_state"] == "HANDOFF_AT_S3"

        _, proj = req("GET", "/api/sim/world-projection")
        assert proj["phase"] == "HANDOFF_AT_S3" and proj["read_only"] is True

        _, rst = req("POST", "/api/sim/reset", {"clear_faults": True})
        assert rst["cargo_state"] == "ON_PINKY" and rst["events"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_slice3_faults_camera_drop_seq_conflict_and_heartbeat_lag() -> None:
    assert len(csc.ALLOWED_FAULTS) == 7
    ctrl = _controller()

    # 5. vision.camera_drop
    north_obs = {"source_id": "ceiling_north", "x_m": 1.0, "y_m": 2.0, "yaw_rad": 0.1, "score": 0.95}
    south_obs = {"source_id": "ceiling_south", "x_m": 0.5, "y_m": 1.5, "yaw_rad": 0.0, "score": 0.91}
    ctrl.faults.enable("vision.camera_drop")
    assert ctrl.faults.apply_vision_boundary(north_obs) is None
    assert ctrl.faults.apply_vision_boundary(south_obs)["source_id"] == "ceiling_south"
    ctrl.faults.enable("vision.camera_drop", {"source_id": None})
    assert ctrl.faults.apply_vision_boundary(south_obs) is None
    ctrl.faults.disable("vision.camera_drop")
    assert ctrl.faults.apply_vision_boundary(north_obs)["score"] == 0.95

    # 6. bridge.seq_conflict_409 (lift + cell stage)
    assert ctrl.handle_s3_arrived_settled(robot_id="rosy_45", dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)["accepted"]
    ctrl.faults.enable("bridge.seq_conflict_409", {"arm_id": "arm_s"})
    lift_blocked = ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)
    assert lift_blocked["accepted"] is False and lift_blocked["status_code"] == 409
    assert lift_blocked["reason"] == "BRIDGE_SEQ_CONFLICT_409:arm_s"
    assert ctrl.cargo_state == "HANDOFF_AT_S3"
    ctrl.faults.disable("bridge.seq_conflict_409")

    assert ctrl.handle_cargo_lifted_or_dropped(arm_id="arm_s", lifted=True, bilateral_lift=True)["accepted"]
    assert ctrl.handle_cell_bed_clear(arm_id="arm_s", arm_in_bed_zone=False)["accepted"]
    assert ctrl.advance_cell_stage("ON_BELT")["accepted"]

    ctrl.faults.enable("bridge.seq_conflict_409")
    stage_blocked = ctrl.advance_cell_stage("IN_CELL_AB")
    assert stage_blocked["accepted"] is False and stage_blocked["status_code"] == 409
    assert stage_blocked["reason"] == "BRIDGE_SEQ_CONFLICT_409:arm_a"
    assert ctrl.cargo_state == "ON_BELT"
    ctrl.faults.disable("bridge.seq_conflict_409")
    assert ctrl.advance_cell_stage("IN_CELL_AB")["cargo_state"] == "IN_CELL_AB"
    assert ctrl.advance_cell_stage("ON_SHIP")["cargo_state"] == "ON_SHIP"

    # 7. hub.heartbeat_lag
    hb_ok = ctrl.faults.apply_hub_heartbeat_boundary("rosy_45", 0.5)
    assert hb_ok["degraded"] is False and hb_ok["fault_injected"] is False
    ctrl.faults.enable("hub.heartbeat_lag", {"robot_id": "rosy_45", "lag_s": 6.0, "threshold_s": 5.0})
    hb_lag = ctrl.faults.apply_hub_heartbeat_boundary("rosy_45", 0.5)
    assert hb_lag["degraded"] is True and hb_lag["fault_injected"] is True
    assert hb_lag["effective_age_s"] == pytest.approx(6.5)
    hb_other = ctrl.faults.apply_hub_heartbeat_boundary("rosy_42", 0.5)
    assert hb_other["degraded"] is False and hb_other["fault_injected"] is False
    ctrl.faults.disable("hub.heartbeat_lag")
    assert ctrl.faults.apply_hub_heartbeat_boundary("rosy_45", 0.5)["degraded"] is False


def test_http_cell_stage_and_bridge_409_roundtrip() -> None:
    ctrl = _controller()
    server = csc.build_server(ctrl, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def post(path: str, body: dict) -> tuple[int, dict]:
        r = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(r, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    try:
        assert post("/api/sim/events/s3-arrived", {"dx_m": 0.0, "dy_m": 0.0, "dyaw_rad": 0.0})[1]["accepted"]
        assert post("/api/sim/events/cargo-lifted", {"lifted": True, "bilateral_lift": True})[1]["accepted"]
        assert post("/api/sim/events/cell-bed-clear", {"arm_in_bed_zone": False})[1]["accepted"]

        post("/api/sim/faults/bridge.seq_conflict_409", {"enabled": True, "params": {"arm_id": "arm_s"}})
        code, blocked = post("/api/sim/events/cell-stage", {"stage": "ON_BELT"})
        assert code == 200 and blocked["accepted"] is False and blocked["status_code"] == 409

        post("/api/sim/faults/bridge.seq_conflict_409", {"enabled": False})
        assert post("/api/sim/events/cell-stage", {"stage": "ON_BELT"})[1]["cargo_state"] == "ON_BELT"
        assert post("/api/sim/events/cell-stage", {"stage": "IN_CELL_AB"})[1]["cargo_state"] == "IN_CELL_AB"
        assert post("/api/sim/events/cell-stage", {"stage": "ON_SHIP"})[1]["cargo_state"] == "ON_SHIP"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
