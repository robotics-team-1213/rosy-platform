"""Unit tests for `tools/capture/slam_pickup_pipeline.py`:
- Preflight sensor/battery gate & LiDAR clearance judgement (`PINKY_PRO`)
- 3-step guarded 360-deg SLAM loop (forward excursion -> 360-deg rotation -> reverse to origin)
- Atomic `site.yaml` / `site.pgm` installation with `rosy-io:rosy-core` `0640` permissions
- Nav2 pickup goal dispatch, arrival polling, dwell, and return-home sequence
- Deterministic stop guarantee (cancel, 3x zero teleop, IDLE, zero-velocity check, service & timer restoration)
- Fleet R peer swarm pose frame `map_id` normalization
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import slam_pickup_pipeline as spp  # noqa: E402


def sample_scan(returns_by_deg: dict[int, float] | None = None, n: int = 360, rest: float = 1.6) -> dict:
    ranges = [rest] * n
    for deg, r in (returns_by_deg or {}).items():
        ranges[(deg + 180) % n] = r
    return {
        "ranges": ranges,
        "angle_min": -math.pi,
        "angle_increment": 2.0 * math.pi / n,
        "range_min": 0.05,
        "range_max": 12.0,
    }


def test_verify_preflight_sensors_accepts_fresh_and_rejects_stale_or_low_battery():
    now = 100.0
    valid = {"scan": object(), "scan_t": 99.8, "odom": object(), "odom_t": 99.9, "volt": 7.73}
    assert spp.verify_preflight_sensors(valid, now) == (True, None)

    assert spp.verify_preflight_sensors({"odom": 1, "odom_t": 99.9, "volt": 7.5}, now) == (False, "missing_scan")
    assert spp.verify_preflight_sensors({**valid, "scan_t": 99.2}, now) == (False, "stale_scan")
    assert spp.verify_preflight_sensors({**valid, "odom_t": 99.1}, now) == (False, "stale_odom")
    assert spp.verify_preflight_sensors({**valid, "volt": 6.85}, now) == (False, "low_battery")


def test_preflight_judge_evaluates_forward_reverse_and_rotation_clearance():
    clear = spp.preflight_judge(sample_scan())
    assert clear["can_rotate"] is True
    assert clear["forward_gap"] > 1.0
    assert clear["reverse_gap"] > 1.0

    # Obstacle right in front (LiDAR forward_deg = 180 deg)
    blocked_front = spp.preflight_judge(sample_scan({d: 0.08 for d in range(170, 191)}))
    assert blocked_front["forward_gap"] < spp.stop_threshold_m()
    assert blocked_front["reverse_gap"] > 1.0


def test_drive_slam_loop_steps_completes_360_turn_and_returns_to_origin():
    calls: list[tuple[str, dict | None]] = []
    pose_state = [0.0, 0.0, 0.0]

    def fake_api(path: str, body: dict | None = None, token: str | None = None):
        calls.append((path, body))
        if path == "/api/v1/robot/state":
            return {"estop": False, "safety": {"estop": False}}
        if path == "/api/v1/teleop" and body:
            pose_state[0] += float(body["linear"]) * 0.5
            pose_state[2] += float(body["angular"]) * 0.9
        return {"ok": True}

    cfg = spp.SlamLoopConfig(forward_m=0.20, turn_rad=2.0 * math.pi)
    res = spp.drive_slam_loop_steps(
        fake_api,
        "tok-1",
        pose_fn=lambda: (pose_state[0], pose_state[1], pose_state[2]),
        judge_fn=lambda: {"forward_gap": 1.5, "reverse_gap": 1.5, "can_rotate": True},
        spin_fn=lambda _: None,
        cfg=cfg,
        sleep_fn=lambda _: None,
    )

    assert res["stop_reason"] == "completed"
    assert res["travelled_fwd_m"] >= 0.20
    assert res["turned_rad"] >= 6.28
    assert res["turned_deg"] >= 360.0
    assert res["travelled_back_m"] >= res["travelled_fwd_m"]
    assert math.isclose(res["end_pose"][0], 0.0, abs_tol=0.05)
    assert calls[-1] == ("/api/v1/mode", {"mode": "IDLE"})


def test_drive_slam_loop_steps_refuses_estop_and_still_executes_finally_stop():
    calls: list[tuple[str, dict | None]] = []

    def fake_api(path: str, body: dict | None = None, token: str | None = None):
        calls.append((path, body))
        if path == "/api/v1/robot/state":
            return {"estop": True}
        return {}

    with pytest.raises(RuntimeError, match="E-Stop active"):
        spp.drive_slam_loop_steps(
            fake_api,
            "tok-1",
            pose_fn=lambda: (0.0, 0.0, 0.0),
            judge_fn=lambda: {"forward_gap": 1.5, "reverse_gap": 1.5, "can_rotate": True},
            spin_fn=lambda _: None,
            sleep_fn=lambda _: None,
        )

    zero_teleops = [c for c in calls if c == ("/api/v1/teleop", {"linear": 0.0, "angular": 0.0})]
    assert len(zero_teleops) >= 3
    assert calls[-1] == ("/api/v1/mode", {"mode": "IDLE"})


def test_install_site_map_files_writes_site_yaml_and_sets_0640_permissions(tmp_path):
    map_base = tmp_path / "mapping_45_loop"
    map_base.with_suffix(".pgm").write_bytes(b"P5\n10 10\n255\n" + b"\x00" * 100)
    map_base.with_suffix(".yaml").write_text(
        yaml.safe_dump({"image": "mapping_45_loop.pgm", "resolution": 0.05, "origin": [-1.98, -3.08, 0]}),
        encoding="utf-8",
    )
    cmds: list[list[str]] = []

    meta = spp.install_site_map_files(map_base, site_dir=tmp_path, run_cmd=lambda cmd, **kw: cmds.append(cmd))
    assert meta["image"] == "site.pgm"
    installed_yaml = yaml.safe_load((tmp_path / "site.yaml").read_text(encoding="utf-8"))
    assert installed_yaml["image"] == "site.pgm"
    assert (tmp_path / "site.pgm").read_bytes().startswith(b"P5")
    assert any(cmd[:2] == ["chown", "rosy-io:rosy-core"] for cmd in cmds)
    assert any(cmd[:2] == ["chmod", "0640"] for cmd in cmds)


def test_dispatch_pickup_and_return_executes_pickup_dwell_and_home_navigation():
    goals: list[dict] = []

    def fake_api(path: str, body: dict | None = None, token: str | None = None):
        if path == "/api/v1/navigation/approval/navigation-start":
            return {"approval": {"valid": True}}
        if path == "/api/v1/system/capabilities":
            return {"navigation": {"goal_navigation": True}}
        if path == "/api/v1/robot/state":
            last = goals[-1] if goals else {"x": 0.0, "y": 0.0, "theta": 0.0}
            return {
                "navigation": "ARRIVED",
                "pose": last,
                "odom_pose": last,
                "velocity": {"linear": 0.0, "angular": 0.0},
            }
        if path == "/api/v1/map":
            return {"width": 76, "height": 71, "resolution": 0.05, "origin": {"x": -1.98, "y": -3.08, "theta": 0.0}}
        if path == "/api/v1/navigation/goal":
            goals.append(body)
            return {"navigation": "NAVIGATING", "goal": body}
        if path == "/api/v1/navigation/state":
            return {"navigation": "ARRIVED", "map_id": "occupancy:9774014e8781", "operation": {"result": "SUCCEEDED"}}
        return {}

    cfg = spp.PickupNav2Config(pickup_x=0.45, pickup_y=0.0, pickup_yaw=0.0, pickup_dwell_s=2.0, return_home=True)
    out = spp.dispatch_pickup_and_return(fake_api, "tok-1", cfg=cfg, sleep_fn=lambda _: None)

    assert out["approval_valid"] is True
    assert goals == [{"x": 0.45, "y": 0.0, "theta": 0.0}, {"x": 0.0, "y": 0.0, "theta": 0.0}]
    assert out["pickup_outcome"]["navigation"] == "ARRIVED"
    assert out["pickup_outcome"]["result"] == "SUCCEEDED"
    assert out["home_outcome"]["navigation"] == "ARRIVED"


def test_deterministic_stop_cancels_zeros_verifies_still_and_restores_services():
    api_calls: list[tuple[str, dict | None]] = []
    cmd_calls: list[list[str]] = []

    def fake_api(path: str, body: dict | None = None, token: str | None = None):
        api_calls.append((path, body))
        if path == "/api/v1/robot/state":
            return {
                "mode": "IDLE",
                "navigation": "IDLE",
                "velocity": {"linear": 0.0, "angular": 0.0},
                "pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
                "odom_pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
            }
        return {}

    def fake_run(cmd: list[str], **kwargs):
        cmd_calls.append(cmd)
        if cmd[:2] == ["systemctl", "is-active"]:
            unit = cmd[2]
            state = "inactive" if unit == "rosy-navigation.service" else "active"
            return SimpleNamespace(stdout=state + "\n")
        return SimpleNamespace(stdout="")

    report = spp.deterministic_stop(fake_api, "tok-1", restore_io_and_timer=True, run_cmd=fake_run, sleep_fn=lambda _: None)

    assert ("/api/v1/navigation/cancel", {}) in api_calls
    assert ("/api/v1/swarm/cancel", {}) in api_calls
    zero_calls = [c for c in api_calls if c == ("/api/v1/teleop", {"linear": 0.0, "angular": 0.0})]
    assert len(zero_calls) == 3
    assert ("/api/v1/mode", {"mode": "IDLE"}) in api_calls
    assert report["robot_still_verified"] is True
    assert report["services"] == {
        "rosy-io.service": "active",
        "rosy-navigation.service": "inactive",
        "rosy-os-update.timer": "active",
    }
    assert ["systemctl", "reset-failed", "rosy-navigation.service"] in cmd_calls
    assert ["systemctl", "start", "rosy-os-update.timer"] in cmd_calls


def test_normalize_swarm_pose_frame_populates_missing_map_id():
    raw = {"type": "swarm.pose", "seq": 12, "payload": {"robot_id": "rosy_46", "map_id": None, "pose": {"x": 0.1, "y": 0.0, "theta": 0.0}}}
    norm = spp.normalize_swarm_pose_frame(raw, "occupancy:9774014e8781")
    assert norm["payload"]["map_id"] == "occupancy:9774014e8781"
    assert raw["payload"]["map_id"] is None
