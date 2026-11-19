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
                flip_second_finger=False, scene_moved=False, cam_moved=False, allow_yaws=None, twin=False,
                jaw_at=None):
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
        # the planner's 180-deg twin: with `twin` every yaw plans the joints of yaw mod 180 (real arm_a 2026-11-17)
        planned = float(pose["yaw_deg"]) % 180.0 if twin else float(pose["yaw_deg"])
        state["pending_yaw"] = planned
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chunks": {"above_pick": [[pose["x"], pose["y"], pose["z"], planned, 0.0, 62.0]]}}))
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
        x, y = fk_x + true_bias_mm[0] / 1000.0 + r_m * math.cos(a), fk_y + true_bias_mm[1] / 1000.0 + r_m * math.sin(a)
        if jaw_at and jaw_at[state["idx"]] == "other":  # the other jaw: jaw_side.other_mm at FK yaw + other_deg
            b = math.radians(state["yaw"] + 79.0)
            x, y = x + 0.054 * math.cos(b), y + 0.054 * math.sin(b)
        return x, y

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


def test_post_eval_twin_yaw_plan_is_no_opposing_pair(tmp_path, monkeypatch):
    # arm_a 2026-11-17: yaw 0 and 180 planned the same joints (IK twin), the pair moved twice to one pose and was
    # refused yaw_pair_gap. Now no pair is chosen whose planned FK yaws are not opposite: one visit, advisory only.
    cfg, _, cal_data, _, _, _ = _make_setup(tmp_path, saved_bias_mm=(0.0, 0.0))
    cell, writer, state = _patch_cell(monkeypatch, true_bias_mm=(9.0, -4.0), twin=True)
    res = cell_post_eval.run_post_eval(cell, cfg, cal_data, apply=True, commissioning=True, person_at_switch=True, write_library_fn=writer)
    assert state["moved"] == [0.0]
    row = res["results"][0]
    assert row["geometry_dependent"] is True and row["status"] == "advisory" and row["reason"] != "yaw_pair_gap"
    assert res["applied"] == [] and res["lateral_xy"]["lateral_xy_verified"] is False


def test_post_eval_labels_the_visible_jaw_over_the_opposing_pair(tmp_path, monkeypatch):
    # the other jaw at both yaws: labelled together, its midpoint is the centre (unlabelled: half 74 mm, finger_identity)
    cfg, _, cal_data, _, _, _ = _make_setup(tmp_path, true_bias_mm=(9.0, -4.0), saved_bias_mm=(0.0, 0.0))
    cell, writer, _ = _patch_cell(monkeypatch, true_bias_mm=(9.0, -4.0), jaw_at=("other", "other"))
    row = cell_post_eval.run_post_eval(cell, cfg, cal_data, commissioning=True, person_at_switch=True, write_library_fn=writer)["results"][0]
    assert row["accepted"] is True and row["jaw_sides"] == ["other", "other"]
    assert row["raw_bias_mm"] == pytest.approx([9.0, -4.0], abs=0.1) and row["half_radius_mm"] == pytest.approx(22.0, abs=0.1)

    # the visible jaw switched between the yaws: both labellings fit, their centres are other_mm apart: refused
    cell_sw, writer_sw, _ = _patch_cell(monkeypatch, true_bias_mm=(9.0, -4.0), jaw_at=("ref", "other"))
    res_sw = cell_post_eval.run_post_eval(cell_sw, cfg, cal_data, apply=True, commissioning=True, person_at_switch=True, write_library_fn=writer_sw)
    assert res_sw["results"][0]["reason"] == "jaw_sides_ambiguous" and res_sw["results"][0]["accepted"] is False
    assert res_sw["applied"] == [] and res_sw["lateral_xy"]["verdict"] == "fail"


def test_blend_bias_at_regularized_kernel_and_sequential_save_fusion(tmp_path):
    data = {
        "schema": cpb.SCHEMA,
        "regions": [
            {"site": "floor", "kind": "pivot", "point_m": [0.10, 0.10], "bias_mm": [10.0, 0.0],
             "radius_mm": 19.5, "phase_deg": 45.0, "centre_sigma_mm": 1.5, "map_sha": "sha_cur"},
            {"site": "floor", "kind": "visit", "point_m": [0.14, 0.10], "bias_mm": [2.0, 0.0],
             "centre_sigma_mm": 2.0, "map_sha": "sha_cur"},
            # Stale map_sha and duplicate region must be ignored by blend_bias_at
            {"site": "floor", "kind": "visit", "point_m": [0.14, 0.10], "bias_mm": [2.0, 0.0],
             "centre_sigma_mm": 2.0, "map_sha": "sha_cur"},
            {"site": "floor", "kind": "visit", "point_m": [0.15, 0.10], "bias_mm": [-20.0, 0.0],
             "centre_sigma_mm": 1.5, "map_sha": "sha_old"},
        ],
    }
    near = cpb.bias_at(data, "floor", [0.12, 0.10], reach_mm=50.0)
    assert near["bias_mm"] == [10.0, 0.0]
    blended = cpb.bias_at(data, "floor", [0.12, 0.10], reach_mm=50.0, blend=True)
    w_piv = 2.0 / (1.5 ** 2 + (20.0 / 15.0) ** 2)
    w_vis = 1.0 / (2.0 ** 2 + (20.0 / 15.0) ** 2)
    assert blended["blended_n"] == 2 and blended["radius_mm"] == 19.5 and blended["phase_deg"] == 45.0
    assert blended["bias_mm"][0] == pytest.approx((w_piv * 10.0 + w_vis * 2.0) / (w_piv + w_vis), abs=0.05)

    # Sequential inverse-variance fusion in save_bias with 1.5mm systematic floor
    bpath = tmp_path / "cal.bias.json"
    cpb.save_bias(bpath, {"site": "floor", "kind": "place_look", "point_m": [0.10, 0.10],
                          "bias_mm": [10.0, 0.0], "centre_sigma_mm": 3.0, "map_sha": "sha1"})
    cpb.save_bias(bpath, {"site": "floor", "kind": "place_look", "point_m": [0.102, 0.10],
                          "bias_mm": [6.0, 4.0], "centre_sigma_mm": 3.0, "map_sha": "sha1"})
    saved = cpb.load_bias(bpath)["regions"]
    assert len(saved) == 1 and saved[0]["bias_mm"] == [8.0, 2.0] and saved[0]["n"] == 2
    assert saved[0]["centre_sigma_mm"] == pytest.approx(max(1.5, 3.0 / math.sqrt(2.0)), abs=0.05)


def test_decompose_rigid_drift_requires_4_points_and_3sigma_significance():
    # n=3 is refused (insufficient DOF for 4-parameter similarity fit)
    pts3 = [[-0.08, 0.15], [0.08, 0.15], [0.0, 0.23]]
    assert cpb.decompose_rigid_drift(pts3, [[4.0, 1.0], [-4.0, 1.0], [0.0, -3.0]])["global_drift"] is False

    pts4 = [[-0.08, 0.14], [0.08, 0.14], [-0.08, 0.24], [0.08, 0.24]]
    # Small unstructured noise does not trigger global drift
    assert cpb.decompose_rigid_drift(pts4, [[2.0, -1.5], [-1.8, 1.2], [1.4, 2.1], [-2.2, -1.0]])["global_drift"] is False

    # True 3.0 deg camera rotation across 4 points triggers rotation_or_scale and escalates
    th = math.radians(3.0)
    c = np.mean(np.asarray(pts4) * 1000.0, axis=0)
    res_rot = [[-th * (p[1] * 1000.0 - c[1]), th * (p[0] * 1000.0 - c[0])] for p in pts4]
    dec = cpb.decompose_rigid_drift(pts4, res_rot, sigma_prior_mm=1.0)
    assert dec["global_drift"] is True and dec["kind"] == "rotation_or_scale"
    assert dec["rot_deg"] == pytest.approx(3.0, abs=0.1) and dec["explained_ratio"] > 0.95

    rows = [{"site": f"s{i}", "point_m": pts4[i], "residual_mm": res_rot[i], "residual_mag_mm": math.hypot(*res_rot[i]),
             "status": "drift", "accepted": True, "map_sha": "sha1"} for i in range(4)]
    cfg = {"sites": {f"s{i}": {"place": pts4[i]} for i in range(4)}}
    is_global, info = cell_post_eval._visit_common_shift(rows, cfg)
    assert is_global is True and info["kind"] == "rotation_or_scale"


def test_wrist_circular_yaw_band_and_loo_outlier_rescue(tmp_path):
    import cell_wrist as cw
    import cell_wrist_cal as cwc

    cal = {"schema": cw.SCHEMA, "arms": {"arm_s": {"camera": "wrist", "bands": [
        {"yaw_lo": 150.0, "yaw_hi": 210.0, "J": [[1.0, 0.0], [0.0, 1.0]], "ref": {"u": 100, "v": 100}},
    ]}}}
    assert cw.band_for(cal, "arm_s", 175.0) is not None
    assert cw.band_for(cal, "arm_s", -175.0) is not None  # wrapped across +/-180!
    assert cw.band_for(cal, "arm_s", 90.0) is None

    # 9-hover grid with 1 outlier at corner (-10, -10) rescued via LOO deletion residual
    xy = [(dx, dy) for dx in (-10.0, 0.0, 10.0) for dy in (-10.0, 0.0, 10.0)]
    uv = [(200.0 + 3.0 * x, 150.0 - 3.0 * y) for x, y in xy]
    uv_bad1 = list(uv)
    uv_bad1[0] = (uv_bad1[0][0] + 45.0, uv_bad1[0][1] - 35.0)
    fitted = cw.fit(xy, uv_bad1)
    assert fitted["dropped_index"] == 0 and fitted["rms_px"] < 0.5

    # 2 outliers still refused
    uv_bad2 = list(uv_bad1)
    uv_bad2[8] = (uv_bad2[8][0] - 40.0, uv_bad2[8][1] + 40.0)
    with pytest.raises(ValueError, match="wrist fit refused"):
        cw.fit(xy, uv_bad2)

    p = tmp_path / "wrist.json"
    cwc.save(p, "arm_s", 170.0, 30.0, fitted, "wrist")
    cwc.save(p, "arm_s", -175.0, 30.0, fitted, "wrist")  # overlaps circularly -> replaces previous
    assert len(json.loads(p.read_text())["arms"]["arm_s"]["bands"]) == 1


def test_cell_calibrate_chains_post_eval_and_depth_verify_and_msac_consensus():
    import cell_calibrate as cc
    import cell_map_fit as cmf

    chk = {"camera_moved": False, "missing_bias": [], "missing_surface": [], "unverified_xy": True, "missing_depth_verify": True}
    assert cc.stale(chk) == ["post-eval", "depth-verify"]

    # MSAC consensus rejects near-collinear triple (height < 0.05*span) and picks lowest error set
    pts = [((100.0 + 1000 * x, 200.0 + 1000 * y), (x, y))
           for x, y in ((0.0, 0.10), (0.04, 0.1002), (0.08, 0.10), (0.0, 0.18), (0.08, 0.18), (0.04, 0.14))]
    kept = cmf.consensus(pts, 5.0)
    assert len(kept) == 6
