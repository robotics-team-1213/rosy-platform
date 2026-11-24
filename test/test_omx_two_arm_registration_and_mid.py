"""Tests for z_view parallax-compensated rigid_of registration and _caps_touch_mid bounds."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
ADAPTER = ROOT / "middleware/devices/omx/adapter"
_ADDED = [str(OMX), str(ADAPTER)]
for _p in _ADDED:
    sys.path.insert(0, _p)
try:
    import cell_calibration as cal_mod  # noqa: E402
    import cell_coordinate as coord_mod  # noqa: E402
    import cell_two_arm_guard as guard_mod  # noqa: E402
    import cell_two_arm_policy_cli as cli_mod  # noqa: E402
finally:
    for _p in _ADDED:
        if _p in sys.path:
            sys.path.remove(_p)


class _DummyKin:
    def link_points(self, joints_rad, fingertip_m=0.0):
        return [(0.0, 0.0, 0.05)] * 6, (0.0, 0.0, -1.0)


def _pinhole_site_record(tx: float, ty: float, theta: float, z_view: float | None, cam: dict) -> dict:
    cx, cy = cam["center_px"]
    depth = cam["height_m"] - (0.11 if z_view is None else z_view)
    f_px = 600.0
    c, s = math.cos(theta), math.sin(theta)
    pairs = []
    for x_arm in (0.05, 0.10, 0.15, 0.20):
        for y_arm in (-0.05, 0.05, 0.10, 0.15):
            wx = c * x_arm - s * y_arm + tx
            wy = s * x_arm + c * y_arm + ty
            u = cx + f_px * ((wx + 0.06) / depth)
            v = cy + f_px * ((wy + 0.10) / depth)
            pairs.append(((u, v), (x_arm, y_arm)))
    rec = cal_mod.site_record(pairs, "2026-11-24T00:00:00")
    if z_view is not None:
        rec["z_view"] = z_view
    return rec


def _setup_cli_files(tmp_path: Path, cam_a: dict | None, cam_b: dict | None, z_a: float | None, z_b: float | None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    cam = {"height_m": 0.596, "center_px": [303, 367]}
    lib_p = tmp_path / "lib.json"
    home = [0.0, -40.0, 40.0, 40.0, 0.0, 50.0]
    lib_p.write_text(json.dumps({
        "fps": 30, "gripper_closed": 47.0,
        "chunks": {"home": [home]},
    }), encoding="utf-8")
    prof_p = tmp_path / "profile.json"
    prof_p.write_text(json.dumps({
        "schema": "rosy.omx-cell-robot-profile.v1",
        "device_id": "dev-1", "instance_id": "arm", "robot_config_sha256": "a" * 64,
        "operating_envelope_path": "rev.json", "work_dir": ".",
    }), encoding="utf-8")
    plan_p = tmp_path / "grasp-plan.json"
    plan_p.write_text((OMX / "grasp-plan.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    cam_prof_p = tmp_path / "cell-profile.json"
    cam_prof_p.write_text(json.dumps({
        "schema": "rosy.omx-cell-profile.v1",
        "top_box": {"roi": [0, 0, 10, 10]},
        "wrist_box": {},
        "reference": {},
        "home": [0.0, -40.0, 40.0, 40.0, 0.0],
    }), encoding="utf-8")
    cal_a, cal_b = tmp_path / "cal_a.json", tmp_path / "cal_b.json"
    cal_a.write_text(json.dumps({"sites": {"belt": _pinhole_site_record(0.34, 0.0, math.pi, z_a, cam)}}), encoding="utf-8")
    cal_b.write_text(json.dumps({"sites": {"belt": _pinhole_site_record(0.0, 0.0, 0.0, z_b, cam)}}), encoding="utf-8")
    cfg_a, cfg_b = tmp_path / "cfg_a.json", tmp_path / "cfg_b.json"
    for cfg_p, cal_p, c in ((cfg_a, cal_a, cam_a), (cfg_b, cal_b, cam_b)):
        cfg_p.write_text(json.dumps({
            "io": str(tmp_path), "cameras": ({"top": c} if c is not None else {}),
            "profile_path": str(cam_prof_p),
            "operating_profile_path": str(prof_p), "calibration_path": str(cal_p), "plan_path": str(plan_p),
        }), encoding="utf-8")
    return cfg_a, cfg_b, lib_p


def test_rigid_of_parallax_symmetry_and_fail_closed_validation():
    cam = {"height_m": 0.596, "center_px": [303, 367]}
    cal_a = {"sites": {"belt": _pinhole_site_record(0.34, 0.0, math.pi, 0.14, cam)}}
    cal_b = {"sites": {"belt": _pinhole_site_record(0.0, 0.0, 0.0, 0.11, cam)}}

    _, tx_no_cam, _ = coord_mod.rigid_of(cal_a, cal_b, "belt", "belt")
    assert abs(tx_no_cam - 0.34) > 0.0025

    for ca, cb in ((cal_a, cal_b), (
        {"sites": {"belt": _pinhole_site_record(0.34, 0.0, math.pi, 0.11, cam)}},
        {"sites": {"belt": _pinhole_site_record(0.0, 0.0, 0.0, 0.14, cam)}},
    )):
        th, tx, ty = coord_mod.rigid_of(ca, cb, "belt", "belt", camera=cam)
        assert abs(math.atan2(math.sin(th - math.pi), math.cos(th - math.pi))) < math.radians(0.1)
        assert tx == pytest.approx(0.34, abs=5e-4) and ty == pytest.approx(0.0, abs=5e-4)

    cal_b_same = {"sites": {"belt": _pinhole_site_record(0.0, 0.0, 0.0, 0.14, cam)}}
    _, tx_same, _ = coord_mod.rigid_of(cal_a, cal_b_same, "belt", "belt")
    assert tx_same == pytest.approx(0.34, abs=1e-6)

    for bad_cam in (
        {"height_m": float("inf"), "center_px": [303, 367]},
        {"height_m": float("nan"), "center_px": [303, 367]},
        {"height_m": 0.14, "center_px": [303, 367]},
        {"height_m": 0.10, "center_px": [303, 367]},
        {"height_m": 0.596, "center_px": [303]},
        {"height_m": 0.596, "center_px": [float("nan"), 367]},
        {"height_m": 0.596, "center_px": [True, 367]},
    ):
        with pytest.raises(ValueError):
            coord_mod.rigid_of(cal_a, cal_b, "belt", "belt", camera=bad_cam)

    cal_none = {"sites": {"belt": _pinhole_site_record(0.0, 0.0, 0.0, None, cam)}}
    with pytest.raises(ValueError, match="asymmetric"):
        coord_mod.rigid_of(cal_a, cal_none, "belt", "belt", camera=cam)

    for bad_z in (float("nan"), float("-inf"), True):
        cal_bad = {"sites": {"belt": {**cal_a["sites"]["belt"], "z_view": bad_z}}}
        with pytest.raises(ValueError):
            coord_mod.rigid_of(cal_bad, cal_b, "belt", "belt")


def test_shared_top_camera_and_cli_gates(tmp_path, monkeypatch):
    cam = {"height_m": 0.596, "center_px": [303, 367]}
    assert coord_mod.shared_top_camera({"cameras": {"top": cam}}, {"cameras": {}}) == {"height_m": 0.596, "center_px": (303.0, 367.0)}
    assert coord_mod.shared_top_camera({"cameras": {}}, {"cameras": {"top": cam}}) == {"height_m": 0.596, "center_px": (303.0, 367.0)}
    with pytest.raises(ValueError, match="center_px disagree"):
        coord_mod.shared_top_camera(
            {"cameras": {"top": {"height_m": 0.596, "center_px": [309, 373]}}},
            {"cameras": {"top": {"height_m": 0.596, "center_px": [297, 361]}}},
        )
    with pytest.raises(ValueError, match="height_m disagree"):
        coord_mod.shared_top_camera(
            {"cameras": {"top": {"height_m": 0.620, "center_px": [303, 367]}}},
            {"cameras": {"top": {"height_m": 0.596, "center_px": [303, 367]}}},
        )

    monkeypatch.setattr(cli_mod.cell_two_arm, "open_cells", lambda *_a, **_kw: {"a": SimpleNamespace(close=lambda: None), "b": SimpleNamespace(close=lambda: None)})
    monkeypatch.setattr(cli_mod.cell_two_arm, "kinematics_for", lambda *_a, **_kw: {"a": SimpleNamespace(), "b": SimpleNamespace()})
    monkeypatch.setattr(cli_mod.cell_two_arm, "away_from_home", lambda *_a, **_kw: [])
    monkeypatch.setattr(cli_mod.cell_policy_handoff, "Authorization", lambda _cfg: (lambda *_a: {}))
    monkeypatch.setattr(cli_mod.cell_remote_policy, "RemotePolicyShadow", lambda *_a, **_kw: SimpleNamespace(goal_size=None, sim_rule=None))
    monkeypatch.setattr(cli_mod, "TwoArmChunkGuard", lambda *_a, **_kw: SimpleNamespace())
    monkeypatch.setattr(cli_mod, "run_two_arm_policy", lambda *_a, **_kw: {"result": "dry_run", "task_id": "T1_CONCURRENT_ZONE_SPLIT"})

    cfg_a, cfg_b, lib_p = _setup_cli_files(tmp_path / "b_only", None, cam, 0.14, 0.11)
    seen = {}
    orig_rigid = cli_mod.cell_coordinate.rigid_of
    monkeypatch.setattr(
        cli_mod.cell_coordinate, "rigid_of",
        lambda ca, cb, sa, sb, *, camera=None: seen.__setitem__("cam", camera) or orig_rigid(ca, cb, sa, sb, camera=camera),
    )
    common_args = [
        "--config-a", str(cfg_a), "--config-b", str(cfg_b),
        "--endpoint-url", "http://127.0.0.1:8790",
        "--revision-a", "a" * 64, "--revision-b", "b" * 64,
        "--library-a", str(lib_p), "--library-b", str(lib_p),
        "--task-a", "belt->temp_a:r1-s1-t1", "--task-b", "temp_b:r1-s1-t1->temp_b:r2-s1-t1",
        "--work-dir", str(tmp_path / "work"), "--proposer", "alice", "--operator", "bob",
    ]
    assert cli_mod.main([*common_args, "--dry-run"]) == 0
    assert seen["cam"] == {"height_m": 0.596, "center_px": (303.0, 367.0)}

    monkeypatch.setattr(cli_mod.cell_coordinate, "rigid_of", orig_rigid)
    cfg_a2, cfg_b2, lib_p2 = _setup_cli_files(tmp_path / "no_cam_live", None, None, 0.14, 0.11)
    with pytest.raises(SystemExit, match="z_view"):
        cli_mod.main([
            "--config-a", str(cfg_a2), "--config-b", str(cfg_b2), *common_args[4:],
            "--commissioning", "--person-at-switch",
        ])


def test_caps_touch_mid_and_guard_fail_closed_validation(monkeypatch):
    rigids = {"a": (0.0, 0.0, 0.0), "b": (0.0, 0.34, 0.0)}
    assert guard_mod._caps_touch_mid([[((0.15, 0.0, 0.04), (0.02, 0.0, 0.08), 0.01)]], rigids, 0.05) is True
    assert guard_mod._caps_touch_mid([[((0.02, 0.0, 0.04), (0.30, 0.0, 0.08), 0.01)]], rigids, 0.05) is True
    assert guard_mod._caps_touch_mid([[((0.0, 0.0, 0.04), (0.06, 0.0, 0.08), 0.02), ((0.06, 0.0, 0.08), (0.24, 0.0, 0.08), 0.02)]], rigids, 0.05) is True
    assert guard_mod._caps_touch_mid([[((0.0, 0.0, 0.04), (0.05, 0.0, 0.08), 0.02), ((0.05, 0.0, 0.08), (0.10, 0.0, 0.08), 0.048)]], rigids, 0.05) is True
    assert guard_mod._caps_touch_mid([[((0.0, 0.0, 0.04), (0.02, 0.0, 0.08), 0.02), ((0.02, 0.0, 0.08), (0.06, 0.0, 0.08), 0.02)]], rigids, 0.05) is False
    assert guard_mod._caps_touch_mid([[((0.0, 0.14, 0.05), (0.0, 0.20, 0.05), 0.01)]], {"a": (0.0, 0.0, 0.0), "b": (0.0, 0.0, 0.34)}, 0.05) is True
    assert guard_mod._caps_touch_mid([[((0.17, 0.0, 0.05), (0.17, 0.0, 0.05), 0.02)]], rigids, 0.0) is False
    assert guard_mod._caps_touch_mid([[((0.0, 0.0, 0.05), (0.01, 0.0, 0.05), 0.01)]], rigids, float("nan")) is True
    assert guard_mod._caps_touch_mid([[((5.0, 5.0, 0.05), (5.0, 5.0, 0.05), 0.01)]], {"a": (0.0, 0.0, 0.0), "b": (0.0, 0.0, 0.0)}, 0.05) is True

    kins = {"a": _DummyKin(), "b": _DummyKin()}
    tips = {"a": 0.074, "b": 0.074}
    for kw in (
        {"rigids": {"a": (0.0, float("nan"), 0.0), "b": (0.0, 0.34, 0.0)}, "tips": tips},
        {"rigids": rigids, "tips": {"a": float("nan"), "b": 0.074}},
        {"rigids": rigids, "tips": tips, "margin_m": float("nan")},
        {"rigids": rigids, "tips": tips, "min_z_m": float("inf")},
        {"rigids": rigids, "tips": tips, "mid_y_band": -0.01},
        {"rigids": rigids, "tips": tips, "mid_y_band": float("nan")},
        {"rigids": rigids, "tips": tips, "wait_timeout_s": float("inf")},
    ):
        r = kw.pop("rigids")
        t = kw.pop("tips")
        with pytest.raises(ValueError):
            guard_mod.TwoArmChunkGuard(kins, r, t, **kw)

    g = guard_mod.TwoArmChunkGuard(kins, rigids, tips, margin_m=0.02, min_z_m=-0.02)
    g.update_pose("a", [0.0] * 6)
    g.update_pose("b", [0.0] * 6)
    monkeypatch.setattr(guard_mod.coordination, "clearance", lambda *_a: float("nan"))
    res = g.admit_chunk("a", [[0.0] * 6])
    assert res == {"admitted": False, "reason": "stationary_collision", "clearance_m": None}
