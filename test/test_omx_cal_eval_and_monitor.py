"""Targeted tests for consolidated calibration fit, monitor, sigma, and safety gates."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/robot/omx"))

import cell_attempts  # noqa: E402
import cell_cal_eval  # noqa: E402
import cell_cal_monitor  # noqa: E402
import cell_calibrate_auto as cca  # noqa: E402
import cell_map_fit  # noqa: E402
import cell_pivot_bias as cpb  # noqa: E402
import cell_surface  # noqa: E402
import cell_wrist_cal  # noqa: E402
import omx_tcp  # noqa: E402


def test_learn_bias_preserves_pivot_circle_writes_map_sha_and_logs_rejected(tmp_path):
    cal_path = tmp_path / "map.json"
    rec = {"homography": [[1e-3, 0, -0.2], [0, 1e-3, -0.1], [0, 0, 1]], "points": []}
    cal_data = {"schema": "rosy.omx-cell-calibration.v1", "sites": {"pinky": rec}}
    cal_path.write_text(json.dumps(cal_data), encoding="utf-8")
    expected_sha = cell_attempts.digest(rec)
    cpb.save_bias(cpb.bias_path(cal_path), {
        "site": "pinky", "kind": "pivot", "point_m": [0.10, 0.20],
        "bias_mm": [2.0, -1.0], "radius_mm": 12.0, "phase_deg": 5.0, "map_sha": expected_sha,
    })
    cfg = {"arm_id": "arm_b", "work_dir": str(tmp_path)}
    out = cca.learn_bias(cfg, cal_path, "pinky", [0.101, 0.201], {"found": True, "seen_bias_mm": [3.0, -1.0], "used_bias_mm": [2.0, -1.0]}, calibration=cal_data)
    assert out is not None and out["kind"] == "place_look" and out["map_sha"] == expected_sha
    regions = cpb.load_bias(cpb.bias_path(cal_path))["regions"]
    assert any(r.get("radius_mm") == 12.0 for r in regions)
    assert any(r.get("kind") == "place_look" and r.get("map_sha") == expected_sha for r in regions)

    # Out-of-window innovation is refused from bias.json, yet raw observation still hits cal-monitor.jsonl.
    rej = cca.learn_bias(cfg, cal_path, "pinky", [0.101, 0.201], {"found": True, "seen_bias_mm": [18.0, 0.0], "used_bias_mm": [2.0, -1.0]}, calibration=cal_data)
    huge = cca.learn_bias(cfg, cal_path, "pinky", [0.101, 0.201], {"found": True, "seen_bias_mm": [80.0, 0.0], "used_bias_mm": [2.0, -1.0]}, calibration=cal_data)
    assert rej is None and huge is None
    assert cpb.bias_at(cpb.load_bias(cpb.bias_path(cal_path)), "pinky", [0.101, 0.201], pivot_only=True)["radius_mm"] == 12.0
    rows = cell_cal_monitor.load_observations(cell_cal_monitor.monitor_path(cfg), arm_id="arm_b")
    assert len(rows) == 3 and rows[-2]["reason"] == "exceeds_bias_learn_max_mm" and rows[-1]["reason"] == "exceeds_max_bias"


def test_map_fit_repair_and_projective_predict_sigma(monkeypatch):
    pts = [([100 + 20 * i, 120 + 15 * j], [0.02 * i, 0.015 * j]) for i in range(3) for j in range(3)]
    rec = {
        "z_view": 0.14,
        "homography": [[1e-3, 0.0, -0.1], [0.0, 1e-3, -0.12], [2e-5, -1e-5, 1.0]],
        "loo_error_mm": {"max": 1.2, "mean": 0.7},
        "points": [{"pixel": list(px), "arm_m": list(arm)} for px, arm in pts],
    }
    near_sig = cell_map_fit.predict_sigma_mm(rec, (120, 135))
    far_sig = cell_map_fit.predict_sigma_mm(rec, (420, 400))
    assert far_sig > near_sig >= 0.7

    bad = {**rec, "homography": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]}
    assert cell_map_fit.predict_sigma_mm(bad, (100, 120)) == 0.7

    import cell_intrinsics_frames as cif
    pose_stub = {"homography": np.eye(3).tolist(), "camera_in_base": {"R": np.eye(3).tolist(), "t": [0, 0, 0.8]}, "loo_error_mm": {"max": 0.9, "mean": 0.5}}
    monkeypatch.setattr(cif, "fitted_map", lambda config, kept, z_view: dict(pose_stub))
    repaired = cell_map_fit.repair_record({}, {"homography": np.eye(3).tolist(), "affine_fit": True, "points": []}, pts[:5])
    assert "affine_fit" not in repaired and "camera_in_base" in repaired and len(repaired["points"]) == 5


def test_surface_and_wrist_cal_cli_hold_without_commissioning_and_switch(tmp_path, capsys):
    cfg = tmp_path / "arm.json"
    cfg.write_text("{}", encoding="utf-8")
    assert cell_surface.main(["--config", str(cfg), "--site", "pinky"]) == 2
    assert "held" in json.loads(capsys.readouterr().out)
    assert cell_wrist_cal.main(["--config", str(cfg), "--site", "pinky", "--x", "0", "--y", "0.2", "--yaw", "0"]) == 2
    assert "held" in json.loads(capsys.readouterr().out)


def test_circle_center_sigma_and_monitor_common_vs_local_and_sha_reset(tmp_path):
    angs = np.linspace(0, 2.2, 6)
    circle = [[0.10 + 0.012 * np.cos(a), 0.20 + 0.012 * np.sin(a)] for a in angs]
    sig = cpb.circle_center_sigma_mm(circle, 0.10, 0.20, 0.001)
    assert sig is not None and sig >= 3.0
    assert cpb.circle_center_sigma_mm([[0.1, 0.2], [0.2, 0.2]], 0.1, 0.2, 0.001) is None

    rec_a = {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
    rec_b = {"homography": [[1, 0, 0.01], [0, 1, 0], [0, 0, 1]]}
    cal_data = {"sites": {"site_a": rec_a, "site_b": rec_b}}
    sha_a, sha_b = cell_attempts.digest(rec_a), cell_attempts.digest(rec_b)
    cfg = {"arm_id": "arm_a", "work_dir": str(tmp_path), "sites": {"site_a": {}, "site_b": {}}}

    # Phase I clean baseline (15 pts each) + common +x shift (8 pts each) -> "common" / "remap"
    for sha, site in ((sha_a, "site_a"), (sha_b, "site_b")):
        for _ in range(15):
            cell_cal_monitor.record_observation(cfg, site=site, map_sha=sha, source="place_look", raw_mm=[1.0, 0.0], residual_mm=[0.4, -0.2], sigma_mm=3.0)
        for _ in range(8):
            cell_cal_monitor.record_observation(cfg, site=site, map_sha=sha, source="place_look", raw_mm=[12.0, 1.0], residual_mm=[9.0, 0.5], sigma_mm=3.0)
    common = cell_cal_monitor.summarize(cfg, cal_data)
    assert common["pattern"] == "common" and common["suggested_advisory"] == ["remap"]

    # Shared map_sha across distinct real sites must trigger common-mode remap, while map_from/tier_of aliases must not
    shared_cal = {"sites": {"site_a": rec_a, "site_b": rec_a}}
    cfg_alias = {**cfg, "sites": {"site_a": {}, "site_b": {"map_from": "site_a"}}}
    for _ in range(15):
        cell_cal_monitor.record_observation(cfg, site="site_b", map_sha=sha_a, source="place_look", raw_mm=[1.0, 0.0], residual_mm=[0.4, -0.2], sigma_mm=3.0)
    for _ in range(8):
        cell_cal_monitor.record_observation(cfg, site="site_b", map_sha=sha_a, source="place_look", raw_mm=[12.0, 1.0], residual_mm=[9.0, 0.5], sigma_mm=3.0)
    assert cell_cal_monitor.summarize(cfg, shared_cal)["pattern"] == "common"
    assert cell_cal_monitor.summarize(cfg_alias, shared_cal)["pattern"] != "common"

    # Mixed look (1D mark_sigma=3.0) + place_look (1D hypot=4.24) baseline must NOT falsely NIS-alarm
    mixed_ok = cell_cal_monitor.evaluate_site_series([
        {"raw_mm": [1.0, 0.0], "residual_mm": [3.5, 2.0], "sigma_mm": 3.0, "source": "look", "accepted": True},
        {"raw_mm": [1.0, 0.0], "residual_mm": [3.5, 2.0], "sigma_mm": 4.24, "source": "place_look", "accepted": True},
    ])
    assert mixed_ok["nis_alarm"] is False and mixed_ok["latest_nis"] < 2.0

    # New map_sha resets active drift evaluation back to unknown (old-map alarms do not leak across remap)
    new_cal = {"sites": {"site_a": {"homography": [[1, 0, 0.05], [0, 1, 0], [0, 0, 1]]}, "site_b": rec_b}}
    after_remap = cell_cal_monitor.summarize(cfg, new_cal)
    assert after_remap["sites"]["site_a"]["n"] == 0 and after_remap["pattern"] == "local" and after_remap["suggested_advisory"] == ["pivot-near site_b"]


def test_omx_tcp_fallback_and_eval_verdict_states():
    assert omx_tcp.config_tcp({"tcp_x_m": 0.074}, {"tcp_x_m": 0.0}) == 0.074
    assert omx_tcp.config_tcp({}, {"tcp_x_m": 0.068}) == 0.068
    unk = cell_cal_eval.build_cross_verify(
        {"a": {"cross_verify_flags": [], "map": {"loo_error_mm": {"max": 1.0}}}},
        None, [{"stale_map": False, "bias_sigma_mm": 1.5}], {"present": False, "stale": True}, None,
    )
    assert unk["eval_verdict"] == "unknown" and unk["lateral_xy_verified"] is False
    adv = cell_cal_eval.build_cross_verify(
        {"a": {"depth_surface_z": 0.02, "touch_surface_z": 0.02, "cross_verify_flags": [], "map": {"loo_error_mm": {"max": 1.0}}}},
        {"sites": {"a": {}}}, [{"stale_map": False, "bias_sigma_mm": 1.5}], {"present": True, "stale": False, "tcp": {"z": 0.1}}, None,
        drift={"alarmed_sites": ["a"], "pattern": "local", "suggested_advisory": ["pivot-near a"]},
    )
    assert adv["eval_verdict"] == "advisory" and adv["lateral_xy_verified"] is False


def test_plan_leverage_and_rgb_only_verify_capture_skip(tmp_path):
    patch = [[-0.11, 0.11], [-0.11, 0.17], [-0.09, 0.11], [-0.09, 0.17]]
    sites = {"pinky": {"place": [0.02, 0.18], "start": [-0.09, 0.14]}}
    tight = cell_map_fit.plan_leverage(patch, sites, sigma_mark_mm=3.0)
    assert tight["sites"]["pinky"]["place_sigma_mm"] > 10.0
    wide = cell_map_fit.plan_leverage(patch + [[0.00, 0.21], [-0.03, 0.21]], sites, sigma_mark_mm=3.0)
    assert wide["sites"]["pinky"]["place_sigma_mm"] < 5.0 and wide["sites"]["pinky"]["place_sigma_mm"] < tight["sites"]["pinky"]["place_sigma_mm"] * 0.5

    cfg_path = tmp_path / "arm_s.json"
    work = tmp_path / "w"
    cfg_path.write_text(json.dumps({
        "arm_id": "arm_s", "work_dir": str(work), "sites": {},
        "cameras": {"top": {"url": "http://127.0.0.1:1/frame/arm_s_top.jpg", "device": "/dev/v4l/by-id/rosy-arm_s_jieli"}},
    }), encoding="utf-8")
    called = []
    rc = cell_cal_eval.verify_main(["--config", str(cfg_path), "--capture", "--write"], capture_fn=lambda: called.append(1))
    assert rc == 0 and called == []
    written = json.loads((work / "depth-verify.json").read_text(encoding="utf-8"))
    assert written["camera_top"]["depth_capture_skipped"] == "rgb_only_top_camera" and written["eval_verdict"] == "unknown"
