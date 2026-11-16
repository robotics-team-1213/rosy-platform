"""Unit tests for yaw-aware pivot fit, D-911 post-calibration XY verification, and bounded visit compensation."""
import json
import math
import sys
import types
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))

import cell_attempts  # noqa: E402
import cell_cal_eval  # noqa: E402
import cell_cal_monitor  # noqa: E402
import cell_calibration_view as ccv  # noqa: E402
import cell_look  # noqa: E402
import cell_pivot  # noqa: E402
import cell_pivot_bias as cpb  # noqa: E402
import cell_post_eval  # noqa: E402


def _synth_marks(centre, yaws_deg, radius_m=0.024, phase_deg=53.0, noise=None):
    out = []
    for i, y in enumerate(yaws_deg):
        a = math.radians(y + phase_deg)
        dx, dy = noise[i] if noise else (0.0, 0.0)
        out.append((centre[0] + radius_m * math.cos(a) + dx, centre[1] + radius_m * math.sin(a) + dy))
    return out


def test_fit_pivot_yaw_narrow_arc_outlier_trim_and_finger_switch_refusal():
    yaws_78 = [-12.0, 8.0, 28.0, 48.0, 66.0]
    marks_narrow = _synth_marks((0.104, -0.095), yaws_78, radius_m=0.022, phase_deg=53.0)
    fit = cpb.fit_pivot_yaw(marks_narrow, yaws_78, mark_sigma_mm=3.0)
    assert fit["result"] == "fitted"
    assert fit["centre_m"] == pytest.approx([0.104, -0.095], abs=1e-4)
    assert fit["radius_mm"] == pytest.approx(22.0, abs=0.2)
    assert fit["phase_deg"] == pytest.approx(53.0, abs=0.5)
    assert fit["centre_sigma_mm"] <= 3.5

    # Single bad outlier out of 7 points is trimmed and centre still recovered.
    yaws_7 = [-120, -80, -40, 0, 40, 80, 120]
    marks_1out = _synth_marks((0.072, 0.055), yaws_7, radius_m=0.0188, phase_deg=53.0)
    marks_1out[2] = (marks_1out[2][0] + 0.030, marks_1out[2][1] - 0.025)
    trimmed = cpb.fit_pivot_yaw(marks_1out, yaws_7, mark_sigma_mm=3.0)
    assert trimmed["result"] == "fitted" and trimmed["dropped"] == 1 and trimmed["n"] == 6
    assert trimmed["centre_m"] == pytest.approx([0.072, 0.055], abs=1e-4)

    # Finger switch on 3 of 7 points must be refused, never averaged.
    marks_split = list(_synth_marks((0.072, 0.055), yaws_7, radius_m=0.022, phase_deg=53.0))
    alt = _synth_marks((0.072, 0.055), yaws_7, radius_m=0.034, phase_deg=282.5)
    for idx in (4, 5, 6):
        marks_split[idx] = alt[idx]
    refused = cpb.fit_pivot_yaw(marks_split, yaws_7, mark_sigma_mm=3.0)
    assert refused["result"] == "refused"


def _make_setup(tmp_path, *, true_bias_mm=(8.0, -5.0), saved_bias_mm=(0.0, 0.0), sites=None):
    cal_path = tmp_path / "map.json"
    site_names = list((sites or {"beltend": {"place": [0.10, 0.18], "yaw_deg": 0.0, "surface_z": 0.01}}).keys())
    rec = {"homography": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], "z_view": 0.08,
           "loo_error_mm": {"max": 1.0, "mean": 0.6}, "points": [{"pixel": [10, 10], "arm_m": [0.1, 0.1]}] * 5}
    cal_data = {"schema": "rosy.omx-cell-calibration.v1", "sites": {s: rec for s in site_names}}
    cal_path.write_text(json.dumps(cal_data), encoding="utf-8")
    map_sha = cell_attempts.digest(rec)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps({"approach_m": 0.04, "limits": {"max_reach_m": 0.4}}), encoding="utf-8")
    ref_path = tmp_path / "ref.jpg"
    ref_path.write_bytes(b"ref")
    pivot_region = {"site": site_names[0], "kind": "pivot", "point_m": [0.10, 0.18],
                    "bias_mm": list(saved_bias_mm), "radius_mm": 22.0, "phase_deg": 53.0, "map_sha": map_sha}
    cpb.save_bias(cpb.bias_path(cal_path), pivot_region)
    cfg = {
        "arm_id": "arm_a",
        "work_dir": str(tmp_path),
        "io": str(tmp_path),
        "calibration_path": str(cal_path),
        "plan_path": str(plan_path),
        "plan": {"approach_m": 0.04},
        "coarse": {"z_view": 0.08},
        "cameras": {"top": {"height_m": 0.6, "center_px": [320, 240]}},
        "preflight": {"reference_top": str(ref_path)},
        "sites": sites or {site_names[0]: {"place": [0.10, 0.18], "yaw_deg": 0.0, "surface_z": 0.01}},
        "params": {},
    }
    cfg_path = tmp_path / "arm.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg, cfg_path, cal_data, cal_path, map_sha, true_bias_mm


def _patch_cell(monkeypatch, *, yaws=(0.0, 180.0), true_bias_mm=(8.0, -5.0), droop_mm=(0.0, 0.0),
                flip_second_finger=False, scene_moved=False, cam_moved=False, allow_yaws=None):
    import cell_calibrate
    import cell_scene_guard
    import joint_jitter

    state = {"idx": -1, "yaw": 0.0, "moved": []}
    monkeypatch.setattr(cell_calibrate, "check", lambda *a, **k: {"camera_moved": cam_moved})
    monkeypatch.setattr(cell_scene_guard, "scene_moved", lambda *a, **k: ["moved"] if scene_moved else [])
    monkeypatch.setattr(cell_post_eval, "_clear_point_for_visit", lambda *a, **k: (True, None))

    def fake_write(cfg, pose, _place, path):
        if allow_yaws is not None and round(pose["yaw_deg"], 1) not in allow_yaws:
            raise SystemExit("joint_min refused")
        state["pending_yaw"] = float(pose["yaw_deg"])
        return path

    monkeypatch.setattr(cell_pivot, "joints_tcp", lambda s, **k: (s[0], s[1], s[2], s[3]))
    monkeypatch.setattr(joint_jitter, "settled_state", lambda cell, p: {
        "state": [0.10 + droop_mm[0] / 1000.0, 0.18 + droop_mm[1] / 1000.0, 0.08, state["yaw"], 0.0],
        "target": [0.10, 0.18, 0.08, state["yaw"], 0.0],
    })
    monkeypatch.setattr(cell_pivot, "mark_jaws", lambda *a, **k: (320.0, 240.0))

    def fake_mark_to_arm(rec, cfg, site, px, fz):
        fk_x = 0.10 + droop_mm[0] / 1000.0
        fk_y = 0.18 + droop_mm[1] / 1000.0
        r_m = 0.0344 if (flip_second_finger and state["idx"] == 1) else 0.022
        ph = 53.0 + (229.5 if (flip_second_finger and state["idx"] == 1) else 0.0)
        a = math.radians(state["yaw"] + ph)
        return (fk_x + true_bias_mm[0] / 1000.0 + r_m * math.cos(a),
                fk_y + true_bias_mm[1] / 1000.0 + r_m * math.sin(a))

    monkeypatch.setattr(cell_pivot, "mark_to_arm", fake_mark_to_arm)

    class FakeCell:
        def __init__(self):
            self.cmds = []

        def frame(self, _cam):
            return np.zeros((32, 32, 3), dtype=np.uint8)

        def act(self, cmd):
            self.cmds.append(cmd)
            if cmd == "goto above_pick":
                state["idx"] += 1
                state["yaw"] = state["pending_yaw"]
                state["moved"].append(state["yaw"])
            return {"ok": True}

    return FakeCell(), fake_write, state


def test_post_eval_cli_holds_without_commissioning_and_escalates_on_camera_shift(tmp_path, monkeypatch, capsys):
    cfg, cfg_path, cal_data, _, _, _ = _make_setup(tmp_path)
    assert cell_post_eval.main(["--config", str(cfg_path)]) == 2
    assert "held" in json.loads(capsys.readouterr().out)

    cell, writer, _ = _patch_cell(monkeypatch, cam_moved=True)
    res = cell_post_eval.run_post_eval(cell, cfg, cal_data, commissioning=True, person_at_switch=True, write_library_fn=writer)
    assert res["verdict"] == "escalate" and res["todo"] == ["remap"] and cell.cmds == []


def test_post_eval_rejects_finger_flip_and_scene_move_and_applies_bounded_visit_preserving_pivot(tmp_path, monkeypatch):
    cfg, _, cal_data, cal_path, map_sha, _ = _make_setup(tmp_path, true_bias_mm=(9.0, -4.0), saved_bias_mm=(0.0, 0.0))

    # 1) Finger identity mismatch rejects and does not apply
    cell_flip, writer_flip, _ = _patch_cell(monkeypatch, true_bias_mm=(9.0, -4.0), flip_second_finger=True)
    res_flip = cell_post_eval.run_post_eval(cell_flip, cfg, cal_data, apply=True, commissioning=True, person_at_switch=True, write_library_fn=writer_flip)
    assert res_flip["results"][0]["reason"] == "finger_identity"
    assert res_flip["applied"] == [] and res_flip["lateral_xy"]["verdict"] == "fail"

    # 2) Scene moved rejects
    cell_mv, writer_mv, _ = _patch_cell(monkeypatch, true_bias_mm=(9.0, -4.0), scene_moved=True)
    res_mv = cell_post_eval.run_post_eval(cell_mv, cfg, cal_data, apply=True, commissioning=True, person_at_switch=True, write_library_fn=writer_mv)
    assert res_mv["results"][0]["reason"] == "scene_moved" and res_mv["applied"] == []

    # 3) Clean opposing-yaw visit with 6mm droop isolates droop_mm, recovers exact 9,-4 bias, preserves pivot circle
    cell_ok, writer_ok, _ = _patch_cell(monkeypatch, true_bias_mm=(9.0, -4.0), droop_mm=(-6.0, 3.0))
    res_ok = cell_post_eval.run_post_eval(cell_ok, cfg, cal_data, apply=True, commissioning=True, person_at_switch=True, write_library_fn=writer_ok)
    row = res_ok["results"][0]
    assert row["status"] == "drift" and row["droop_mm"] == pytest.approx([-6.0, 3.0], abs=0.1)
    assert row["raw_bias_mm"] == pytest.approx([9.0, -4.0], abs=0.1)
    assert len(res_ok["applied"]) == 1 and res_ok["applied"][0]["kind"] == "visit"
    assert "radius_mm" not in res_ok["applied"][0] and "phase_deg" not in res_ok["applied"][0]

    # Pivot region must still exist untouched, and visit region must coexist cleanly!
    saved = cpb.load_bias(cpb.bias_path(cal_path))["regions"]
    assert any(r["kind"] == "pivot" and r["radius_mm"] == 22.0 and r["bias_mm"] == [0.0, 0.0] for r in saved)
    assert any(r["kind"] == "visit" and r["bias_mm"] == pytest.approx([9.0, -4.0], abs=0.1) for r in saved)


def test_post_eval_common_shift_escalates_and_cal_eval_reflects_lateral_xy(tmp_path, monkeypatch):
    sites = {
        "site_a": {"place": [0.10, 0.18], "yaw_deg": 0.0, "surface_z": 0.01},
        "site_b": {"place": [0.12, 0.16], "yaw_deg": 0.0, "surface_z": 0.01},
    }
    cfg, _, cal_data, _, map_sha, _ = _make_setup(tmp_path, sites=sites, saved_bias_mm=(0.0, 0.0))
    cell, writer, _ = _patch_cell(monkeypatch, true_bias_mm=(10.0, 2.0))
    res = cell_post_eval.run_post_eval(cell, cfg, cal_data, apply=True, commissioning=True, person_at_switch=True, write_library_fn=writer)
    assert res["verdict"] == "escalate" and "remap" in res["escalated"] and res["applied"] == []

    # Fresh passing visits flip lateral_xy_verified=True in BOTH verify_profile_depth and build_cross_verify
    cell_pass, writer_pass, _ = _patch_cell(monkeypatch, true_bias_mm=(1.0, -0.5))
    cfg_single = dict(cfg, sites={"site_a": sites["site_a"]})
    res_pass = cell_post_eval.run_post_eval(cell_pass, cfg_single, cal_data, commissioning=True, person_at_switch=True, write_library_fn=writer_pass)
    assert res_pass["lateral_xy"]["lateral_xy_verified"] is True

    report = cell_cal_eval.verify_profile_depth(cfg_single, cal_data)
    assert report["camera_top"]["lateral_xy_verified"] is True
    assert report["lateral_xy"]["verdict"] == "pass"

    cv = cell_cal_eval.build_cross_verify({}, report, [], {"present": False}, None)
    assert cv["lateral_xy_verified"] is True

    # Stale map_sha invalidates lateral_xy_verified back to False!
    new_cal = {"sites": {"site_a": {**cal_data["sites"]["site_a"], "z_view": 0.09}}}
    assert cell_cal_eval.verify_profile_depth(cfg_single, new_cal)["camera_top"]["lateral_xy_verified"] is False


def test_post_eval_1yaw_fallback_is_advisory_and_never_applies(tmp_path, monkeypatch):
    cfg, _, cal_data, _, _, _ = _make_setup(tmp_path, saved_bias_mm=(0.0, 0.0))
    cell, writer, state = _patch_cell(monkeypatch, true_bias_mm=(9.0, -4.0), allow_yaws={0.0})
    res = cell_post_eval.run_post_eval(cell, cfg, cal_data, apply=True, commissioning=True, person_at_switch=True, write_library_fn=writer)
    assert state["moved"] == [0.0]
    assert res["results"][0]["geometry_dependent"] is True and res["results"][0]["status"] == "advisory"
    assert res["applied"] == [] and res["lateral_xy"]["verdict"] == "advisory" and res["lateral_xy"]["lateral_xy_verified"] is False


def test_blend_bias_at_weights_by_distance_and_sigma_preserving_pivot_geometry():
    data = {
        "schema": cpb.SCHEMA,
        "regions": [
            {"site": "floor", "kind": "pivot", "point_m": [0.10, 0.10], "bias_mm": [10.0, 0.0],
             "radius_mm": 19.5, "phase_deg": 45.0, "centre_sigma_mm": 1.0},
            {"site": "floor", "kind": "visit", "point_m": [0.14, 0.10], "bias_mm": [2.0, 0.0],
             "centre_sigma_mm": 2.0},
        ],
    }
    # Default bias_at returns nearest region without blending
    near = cpb.bias_at(data, "floor", [0.12, 0.10], reach_mm=50.0)
    assert near["bias_mm"] == [10.0, 0.0]
    # Midpoint [0.12, 0.10] is 20mm from both; pivot has 2x kind weight and 4x (1/sigma^2) weight -> 8:1 weight ratio
    blended = cpb.bias_at(data, "floor", [0.12, 0.10], reach_mm=50.0, blend=True)
    assert blended["blended_n"] == 2 and blended["radius_mm"] == 19.5 and blended["phase_deg"] == 45.0
    assert blended["bias_mm"][0] == pytest.approx((8.0 * 10.0 + 1.0 * 2.0) / 9.0, abs=0.05)


def test_decompose_rigid_drift_detects_camera_rotation_and_escalates_post_eval():
    pts = [[-0.08, 0.15], [0.08, 0.15], [0.0, 0.23]]
    th = math.radians(2.5)
    c = np.mean(np.asarray(pts) * 1000.0, axis=0)
    res_rot = [[-th * (p[1] * 1000.0 - c[1]), th * (p[0] * 1000.0 - c[0])] for p in pts]
    dec = cpb.decompose_rigid_drift(pts, res_rot)
    assert dec["global_drift"] is True and dec["kind"] == "rotation_or_scale"
    assert dec["rot_deg"] == pytest.approx(2.5, abs=0.1) and dec["explained_ratio"] > 0.95

    rows = [{"site": f"s{i}", "point_m": pts[i], "residual_mm": res_rot[i], "residual_mag_mm": math.hypot(*res_rot[i]),
             "status": "drift", "accepted": True, "map_sha": "sha1"} for i in range(3)]
    cfg = {"sites": {f"s{i}": {"place": pts[i]} for i in range(3)}}
    is_global, info = cell_post_eval._visit_common_shift(rows, cfg)
    assert is_global is True and info["kind"] == "rotation_or_scale"


def test_cell_calibrate_chains_post_eval_and_depth_verify():
    import cell_calibrate as cc

    chk = {"camera_moved": False, "missing_bias": [], "missing_surface": [], "unverified_xy": True, "missing_depth_verify": True}
    assert cc.stale(chk) == ["post-eval", "depth-verify"]
