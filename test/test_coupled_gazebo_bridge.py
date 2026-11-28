"""Tests for Gazebo <-> CoupledSimController HTTP bridge (D-1088 Slice 3)."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIM_DIR = ROOT / "tools" / "sim"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

import coupled_gazebo_bridge as bridge_mod  # noqa: E402
import coupled_sim_controller as csc  # noqa: E402

MAP_SHA = "ef" * 32
S3_LIMITS = {
    "reference_pose": [-0.1914, -0.207, -1.5708],
    "longitudinal_m": 0.05,
    "lateral_m": 0.04,
    "heading_rad": 0.12,
    "position_uncertainty_m": 0.005,
    "heading_uncertainty_rad": 0.01,
}


def _stationary_samples(
    *,
    x: float = -0.1914,
    y: float = -0.207,
    yaw: float = -1.5708,
    linear_m_s: float = 0.002,
    angular_rad_s: float = 0.01,
    count: int = 4,
    dt_s: float = 0.5,
) -> list[dict]:
    return [
        {
            "sim_time_s": 10.0 + idx * dt_s,
            "pose_xy_yaw": [x, y, yaw],
            "linear_m_s": linear_m_s,
            "angular_rad_s": angular_rad_s,
        }
        for idx in range(count)
    ]


def _start_controller_server() -> tuple[csc.CoupledSimController, ThreadingHTTPServer, threading.Thread, str]:
    ctrl = csc.CoupledSimController(site_map_sha256=MAP_SHA)
    srv = csc.build_server(ctrl, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    return ctrl, srv, thread, url


def test_compute_s3_arrival_observation_bounds_velocity_and_rtf() -> None:
    # In-bounds stationary samples: 4 samples spanning 1.5 s over wall 1.5 s -> RTF 1.0
    # Reference yaw is -pi/2: +0.01 in world y projects to -0.01 longitudinal in reference frame.
    ok_samples = _stationary_samples(x=-0.1864, y=-0.197, yaw=-1.5508)
    obs = bridge_mod.compute_s3_arrival_observation(ok_samples, S3_LIMITS, wall_elapsed_s=1.5)
    assert obs["in_bounds"] is True
    assert obs["bed_velocity_measured"] is True
    assert obs["rtf"] == pytest.approx(1.0)
    assert obs["sample_count"] == 4
    assert obs["dx_m"] == pytest.approx(-0.01, abs=1e-4)
    assert obs["dy_m"] == pytest.approx(0.005, abs=1e-4)

    # Out-of-bounds due to longitudinal error + uncertainty exceeding 0.05 m
    oob_samples = _stationary_samples(y=-0.155)
    oob = bridge_mod.compute_s3_arrival_observation(oob_samples, S3_LIMITS, wall_elapsed_s=1.5)
    assert oob["in_bounds"] is False

    # Unmeasured bed velocity (< 4 samples or excess linear/angular speed)
    few = bridge_mod.compute_s3_arrival_observation(_stationary_samples(count=3), S3_LIMITS, wall_elapsed_s=1.0)
    assert few["bed_velocity_measured"] is False
    moving = bridge_mod.compute_s3_arrival_observation(_stationary_samples(linear_m_s=0.025), S3_LIMITS, wall_elapsed_s=1.5)
    assert moving["bed_velocity_measured"] is False

    # Low RTF (< 0.9) when wall clock lags sim time
    slow = bridge_mod.compute_s3_arrival_observation(_stationary_samples(), S3_LIMITS, wall_elapsed_s=2.0)
    assert slow["rtf"] == pytest.approx(0.75)

    with pytest.raises(ValueError):
        bridge_mod.compute_s3_arrival_observation([], S3_LIMITS, wall_elapsed_s=1.0)
    with pytest.raises(ValueError):
        bridge_mod.compute_s3_arrival_observation(_stationary_samples(), S3_LIMITS, wall_elapsed_s=0.0)


def test_bridge_cmd_vel_filter_s3_arrival_and_departure_permissions() -> None:
    ctrl, srv, thread, url = _start_controller_server()
    try:
        bridge = bridge_mod.CoupledGazeboBridge(url, robot_id="rosy_45")

        # Tangled fault clamps cmd_vel for targeted robot only
        assert bridge.filter_cmd_vel(0.25, -0.3) == pytest.approx((0.25, -0.3))
        ctrl.faults.enable("pinky.tangled_or_stall", {"robot_id": "rosy_42"})
        assert bridge.filter_cmd_vel(0.25, -0.3) == pytest.approx((0.25, -0.3))
        ctrl.faults.enable("pinky.tangled_or_stall", {"robot_id": "rosy_45"})
        assert bridge.filter_cmd_vel(0.25, -0.3) == (0.0, 0.0)
        ctrl.faults.disable("pinky.tangled_or_stall")
        assert bridge.filter_cmd_vel(0.25, -0.3) == pytest.approx((0.25, -0.3))

        # S3 arrival report with low RTF triggers inconclusive gate in controller
        obs_slow = bridge_mod.compute_s3_arrival_observation(_stationary_samples(), S3_LIMITS, wall_elapsed_s=2.0)
        s3_res = bridge.report_s3_arrival(obs_slow)
        assert s3_res["accepted"] is True
        assert s3_res["cargo_state"] == "HANDOFF_AT_S3"
        assert s3_res["inconclusive"] is True

        # Blocked while HANDOFF_AT_S3 / arm_in_bed_zone=True
        blocked_bed = bridge.wait_for_departure_permission(timeout_s=0.05, poll_s=0.01)
        assert blocked_bed["permitted"] is False
        assert blocked_bed["reason"] == "ARM_IN_BED_ZONE"

        # Lift succeeds, arm still in bed zone -> blocked; clear -> permitted
        assert ctrl.handle_cargo_lifted_or_dropped(lifted=True, bilateral_lift=True)["accepted"] is True
        assert bridge.check_departure_permission()["permitted"] is False
        assert ctrl.handle_cell_bed_clear(arm_in_bed_zone=False)["pinky_departure_permitted"] is True

        # Stalled fault blocks departure even after bed clear
        ctrl.faults.enable("pinky.tangled_or_stall", {"robot_id": "rosy_45"})
        stalled = bridge.wait_for_departure_permission(timeout_s=0.05, poll_s=0.01)
        assert stalled["permitted"] is False
        assert stalled["reason"] == "PINKY_TANGLED_OR_STALL"
        ctrl.faults.disable("pinky.tangled_or_stall")

        permitted = bridge.wait_for_departure_permission(timeout_s=0.2, poll_s=0.01)
        assert permitted["permitted"] is True
        assert permitted["cargo_state"] == "IN_CELL_ARM_S"

        # CARGO_FAULT fails closed immediately
        ctrl.reset(clear_faults=True)
        obs_ok = bridge_mod.compute_s3_arrival_observation(_stationary_samples(), S3_LIMITS, wall_elapsed_s=1.5)
        assert bridge.report_s3_arrival(obs_ok)["accepted"] is True
        ctrl.handle_cargo_lifted_or_dropped(lifted=False, bilateral_lift=False)
        ctrl.arm_in_bed_zone = False
        fault_hold = bridge.wait_for_departure_permission(timeout_s=1.0, poll_s=0.01)
        assert fault_hold["permitted"] is False
        assert fault_hold["cargo_state"] == "CARGO_FAULT"
        assert fault_hold["reason"] == "CARGO_FAULT_HOLD"

        # Heartbeat evaluation works against current controller fault list
        hb = bridge.evaluate_heartbeat(1.2)
        assert hb["fault_injected"] is False
        assert hb["degraded"] is False
        assert hb["effective_age_s"] == pytest.approx(1.2)
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2.0)


def test_bridge_evaluate_heartbeat_with_injected_lag_fault() -> None:
    class _LagFaultHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            body = json.dumps({
                "schema": "rosy.sim.fault-state.v1",
                "active": {"hub.heartbeat_lag": {"robot_id": "rosy_45", "lag_s": 8.0, "threshold_s": 5.0}},
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _LagFaultHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        bridge = bridge_mod.CoupledGazeboBridge(f"http://127.0.0.1:{srv.server_address[1]}", robot_id="rosy_45")
        hb = bridge.evaluate_heartbeat(1.0)
        assert hb["fault_injected"] is True
        assert hb["effective_age_s"] == pytest.approx(9.0)
        assert hb["degraded"] is True
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2.0)
