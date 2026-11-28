"""End-to-end tests for the 4-layer live coupled simulation sandbox (D-1088 Slice 2)."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time
import urllib.request

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SIM_DIR = ROOT / "tools" / "sim"
if str(SIM_DIR) not in sys.path:
    sys.path.insert(0, str(SIM_DIR))

from coupled_sim_sandbox import CoupledSimSandbox  # noqa: E402

MAP_SHA = "cd" * 32


def _make_world_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    (bundle / "data").mkdir(parents=True)
    (bundle / "index.html").write_text("<html></html>", encoding="utf-8")
    (bundle / "SHA256SUMS.txt").write_text("", encoding="utf-8")
    (bundle / "manifest.json").write_text(
        json.dumps({"inputs": {"site-map/world_261026_v7_active.json": {"sha256": MAP_SHA}}}),
        encoding="utf-8",
    )
    (bundle / "data" / "site-map.json").write_text(
        json.dumps({"version": 7, "map": {"map_id": "world_261026", "places": [{"id": "S3", "x": 0.745, "y": -0.207}], "edges": []}}),
        encoding="utf-8",
    )
    return bundle


def _read_world_sse(world_url: str) -> dict:
    with urllib.request.urlopen(f"{world_url}/sim/stream?world=coupled-sim&max_events=1", timeout=3.0) as res:
        assert res.readline() == b"event: state\n"
        line = res.readline().decode("utf-8")
    assert line.startswith("data: ")
    return json.loads(line[6:])


def test_coupled_sandbox_full_e2e_and_read_only_world_sse(tmp_path: Path) -> None:
    bundle = _make_world_bundle(tmp_path)
    with CoupledSimSandbox(work_dir=tmp_path / "run", world_bundle_dir=bundle, site_map_sha256=MAP_SHA) as sb:
        with TestClient(sb.app) as client:
            st0 = client.get("/api/fleet/state", headers=sb.auth_headers)
            assert st0.status_code == 200 and st0.json()["fleet"]["online"] == 6

            goal = sb.dispatch_pinky_goal(client, x=-0.1914, y=-0.207, yaw=-1.5708, idempotency_key="goal-s3-1")
            assert goal.get("accepted") is True or goal.get("queued") is True

            moved = False
            latest_fleet = None
            for _ in range(50):
                time.sleep(0.1)
                latest_fleet = client.get("/api/fleet/state", headers=sb.auth_headers).json()
                p45 = next(r for r in latest_fleet["robots"] if r["robot_id"] == "rosy_45")
                if p45["state"]["pose"]["y"] < 0.35:
                    moved = True
                    break
            assert moved and latest_fleet is not None

            assert sb.trigger_s3_handoff(dx_m=0.015, dy_m=-0.01, dyaw_rad=0.04)["accepted"] is True
            lift_res, clear_res = sb.complete_arm_s_lift_and_clear(lifted=True, bilateral_lift=True)
            assert lift_res["gazebo_tray_empty"] is True
            assert clear_res is not None and clear_res["pinky_departure_permitted"] is True
            assert sb.advance_downstream_ab()["cargo_state"] == "ON_SHIP"

            time.sleep(0.25)
            latest_fleet = client.get("/api/fleet/state", headers=sb.auth_headers).json()
            sb.sync_world(latest_fleet)

            frame = _read_world_sse(sb.world_url)
            assert frame["parity"]["ok"] is True
            assert frame["read_only"] is True
            assert frame["world_id"] == "coupled-sim" and frame["adapter"] == "gazebo"
            assert frame["phase"] == "ON_SHIP"
            assert frame["pinky"]["has_cargo"] is False
            assert frame["pinky"]["pose_m"][1] < 0.35


def test_live_fault_pinky_tangled_blocks_motion_then_recovers(tmp_path: Path) -> None:
    bundle = _make_world_bundle(tmp_path)
    with CoupledSimSandbox(work_dir=tmp_path / "run", world_bundle_dir=bundle, site_map_sha256=MAP_SHA) as sb:
        with TestClient(sb.app) as client:
            sb.set_fault("pinky.tangled_or_stall", enabled=True, params={"robot_id": "rosy_45"})
            sb.dispatch_pinky_goal(client, x=-0.1914, y=-0.207, yaw=-1.5708, idempotency_key="goal-stall-1")
            time.sleep(0.45)
            st_stalled = client.get("/api/fleet/state", headers=sb.auth_headers).json()
            p45_stalled = next(r for r in st_stalled["robots"] if r["robot_id"] == "rosy_45")
            assert p45_stalled["state"]["pose"]["y"] > 0.46  # Held at start while tangled fault is ON

            sb.sync_world(st_stalled)
            frame = _read_world_sse(sb.world_url)
            assert "pinky.tangled_or_stall" in frame["active_faults"]

            sb.set_fault("pinky.tangled_or_stall", enabled=False)
            resumed = False
            for _ in range(50):
                time.sleep(0.1)
                st_ok = client.get("/api/fleet/state", headers=sb.auth_headers).json()
                p45_ok = next(r for r in st_ok["robots"] if r["robot_id"] == "rosy_45")
                if p45_ok["state"]["pose"]["y"] < 0.35:
                    resumed = True
                    break
            assert resumed


def test_live_faults_s3_brake_arm_unplug_and_vision_mismatch(tmp_path: Path) -> None:
    bundle = _make_world_bundle(tmp_path)
    with CoupledSimSandbox(work_dir=tmp_path / "run", world_bundle_dir=bundle, site_map_sha256=MAP_SHA) as sb:
        with TestClient(sb.app) as client:
            sb.set_fault("pinky.s3_brake_unmeasured", enabled=True)
            r1 = sb.trigger_s3_handoff(dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)
            assert r1["accepted"] is False and r1["reason"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED"
            sb.set_fault("pinky.s3_brake_unmeasured", enabled=False)

            sb.set_fault("arm.usb_unplugged", enabled=True, params={"arm_id": "arm_s"})
            r2 = sb.trigger_s3_handoff(dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)
            assert r2["accepted"] is False and r2["reason"] == "ARM_USB_UNPLUGGED:arm_s"
            sb.sync_world(client.get("/api/fleet/state", headers=sb.auth_headers).json())
            assert _read_world_sse(sb.world_url)["arms_observed"]["arm_s"] is False
            sb.set_fault("arm.usb_unplugged", enabled=False)
            assert sb.trigger_s3_handoff(dx_m=0.0, dy_m=0.0, dyaw_rad=0.0)["accepted"] is True

            raw_obs = {"source_id": "ceiling_north", "x_m": 0.5, "y_m": 0.2, "yaw_rad": 0.0, "score": 0.99}
            sb.set_fault("vision.calibration_mismatch", enabled=True)
            bad = sb.sample_vision_observation(raw_obs)
            assert bad["score"] < 0.5 and bad["calibration_mismatch_injected"] is True
            sb.set_fault("vision.calibration_mismatch", enabled=False)
            assert sb.sample_vision_observation(raw_obs)["score"] == 0.99


def test_real_fleet_estop_halts_all_six_virtual_robots(tmp_path: Path) -> None:
    bundle = _make_world_bundle(tmp_path)
    with CoupledSimSandbox(work_dir=tmp_path / "run", world_bundle_dir=bundle, site_map_sha256=MAP_SHA) as sb:
        with TestClient(sb.app) as client:
            estop = client.post("/api/fleet/estop", headers=sb.auth_headers)
            assert estop.status_code == 200
            halted = False
            for _ in range(15):
                time.sleep(0.2)
                after = client.get("/api/fleet/state", headers=sb.auth_headers).json()
                if all(r["state"]["safety"]["estop"] is True for r in after["robots"]):
                    halted = True
                    break
            assert halted
