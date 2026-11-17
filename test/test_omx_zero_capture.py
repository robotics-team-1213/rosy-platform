"""OMX joint-zero capture tool: plan limits/visibility, noise-free recovery, the PASS/FAIL gate, and a round trip
through real images and the capture file format (markers drawn with cv2.aruco, detected, sub-pixel refined, averaged)."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
pytest.importorskip("scipy")
if not hasattr(cv2, "aruco"):
    pytest.skip("OpenCV without aruco", allow_module_level=True)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
sys.path.insert(0, str(ROOT / "middleware/devices/omx/adapter"))
import omx_zero_capture as zc  # noqa: E402
import omx_zero_model as zm  # noqa: E402
import omx_zero_plan as zp  # noqa: E402
import omx_zero_solve as zs  # noqa: E402
from omx_adapter.z_profile import fk_landmarks_mm  # noqa: E402

SLOT = 2
IDS = zm.cf.slot_ids(SLOT)
MARKER = zm.Marker(IDS["gripper"], 30.0, (45.0, 0.0, 12.0))
SIZE = [1280, 960]
K = [[900.0, 0, 640], [0, 900.0, 480], [0, 0, 1]]
CAM_R = np.array([[0.0, -1, 0], [-1, 0, 0], [0, 0, -1]])  # looks straight down from 650 mm over (150, 0)
CAM_T = np.array([0.15, 0.0, 0.65])
ZERO_TRUE = zm.PRIOR_DEG + np.array([1.5, -2.0, 1.0, 2.0, -1.5])


def square(cx, cy, side=0.04):
    h = side / 2
    return [[cx + h, cy + h, 0.0], [cx + h, cy - h, 0.0], [cx - h, cy - h, 0.0], [cx - h, cy + h, 0.0]]


def record():
    base = dict(zip(IDS["base"], (square(0.03, -0.06), square(0.03, 0.10))))
    return {"K": K, "dist": [0.0] * 5, "size": SIZE, "slot": SLOT, "camera_in_base": {"R": CAM_R.tolist(), "t": CAM_T.tolist()},
            "markers": {str(i): c for i, c in base.items()}, "base": IDS["base"], "surfaces": {}}, base


REC, BASE = record()
CAM = zm.camera_of(REC)


def exact_pose(q_deg, std=0.2, n=9):
    pts = zm.marker_points_mm(q_deg, ZERO_TRUE, MARKER)
    return {"q_deg": np.asarray(q_deg, float), "corners": zm.pixels(pts, REC, CAM), "camera": CAM, "n": n, "std_px": std}


@pytest.fixture(scope="module")
def planned():
    return zp.plan(REC, MARKER, n=14)


def test_chain_matches_z_profile():
    q = np.array([10.0, -20.0, 15.0, 30.0, -40.0])
    p, r = zm.link5_pose(q, zm.PRIOR_DEG, -8.3)
    lm = fk_landmarks_mm(q, unit="deg", joint_zero_offset_deg=zm.PRIOR_DEG, table_z_offset_mm=-8.3)["landmarks_xyz_mm"]
    assert np.abs(p - lm["joint5"]).max() < 2e-3 and np.abs(p + r @ [74.1, 0, 0] - lm["tcp"]).max() < 2e-3
    assert np.abs(p + r @ zm.WRIST_CAM_MM - lm["wrist_cam"]).max() < 2e-3
    assert abs(zm.tcp_z_mm(q, zm.PRIOR_DEG, -8.3) - lm["tcp"][2]) < 2e-3


def test_marker_corner_order_is_clockwise_seen_from_the_face():
    c = zm.Marker(1, 20.0, (0, 0, 0), "+z").local_corners()
    assert np.allclose(c[0], [10, 10, 0]) and np.allclose(c[1], [10, -10, 0]) and np.allclose(c[2], [-10, -10, 0])
    for face in ("+z", "-z", "+x", "-x", "+y", "-y"):
        m = zm.Marker(1, 20.0, (0, 0, 0), face)
        c = m.local_corners()
        assert np.allclose(np.cross(c[1] - c[0], c[3] - c[0]) / 400, -m.normal_local()) or \
            np.allclose(np.cross(c[3] - c[0], c[1] - c[0]) / 400, m.normal_local())


def test_plan_respects_limits_and_visibility(planned):
    assert len(planned["poses"]) == 14 and planned["unit"] == "norm"
    win = zp.window_deg()
    for p in planned["poses"]:
        q = np.array(p["q_deg"])
        assert ((q >= win[:, 0] - 0.01) & (q <= win[:, 1] + 0.01)).all()
        assert zm.view_ok(q, zm.PRIOR_DEG, MARKER, REC)
        assert np.allclose(np.array(p["q_norm"]) * 1.8, q, atol=0.002)
    assert max(planned["predicted_sigma_deg"]) <= 0.25  # at the plan's 1 px
    assert planned["travel_deg"]["ordered"] <= planned["travel_deg"]["as_picked"]
    assert np.ptp([p["q_deg"][3] for p in planned["poses"]]) > 40 and np.ptp([p["q_deg"][4] for p in planned["poses"]]) > 60


def test_plan_obeys_cell_config_limits():
    cfg = {"joint_max": {"wrist_flex.pos": 10.0}, "joint_min": {"wrist_roll.pos": 5.0}}
    out = zp.plan(REC, MARKER, cfg, n=12)
    assert max(p["q_norm"][3] for p in out["poses"]) <= 10.0 and min(p["q_norm"][4] for p in out["poses"]) >= 5.0
    with pytest.raises(ValueError):
        zp.plan(REC, MARKER, n=20)
    with pytest.raises(ValueError):
        zp.window_deg({"joint_max": {"wrist_flex.pos": -50.0}})


def test_noise_free_recovery_and_table(planned):
    poses = [exact_pose(p["q_deg"]) for p in planned["poses"]]
    out = zs.solve(poses, MARKER, REC)
    assert out["verdict"] == "PASS" and np.abs(np.array(out["zero_deg"]) - ZERO_TRUE).max() < 0.01
    assert out["held_out_px"]["median"] < 0.05
    q_touch = np.array([0.0, 37.0, -10.0, 50.0, 0.0]) + ZERO_TRUE
    table_true = -6.5
    touch = {"q_deg": q_touch, "z_mm": zm.tcp_z_mm(q_touch, ZERO_TRUE, table_true)}
    out = zs.solve(poses, MARKER, REC, touch=touch)
    assert abs(out["table_offset_mm"] - table_true) < 0.5 and out["table_sigma_mm"] > 0


def test_free_camera_absorbs_a_bad_base_solve(planned):
    """A base-marker-only camera is soft (0.1 px moves it 3-4 mm): a camera 2 deg / 20 mm off must not shift the zeros."""
    cam_bad = zs.bumped(CAM, np.array([1.0, -0.5, 0.8, 15.0, -10.0, 8.0]))
    poses = [dict(exact_pose(p["q_deg"]), camera=CAM) for p in planned["poses"]]
    base = {i: zm.pixels(np.array(c) * 1000.0, REC, CAM) for i, c in BASE.items()}
    out = zs.solve([dict(p, camera=cam_bad) for p in poses], MARKER, REC, base=base)
    assert out["verdict"] == "PASS" and np.abs(np.array(out["zero_deg"]) - ZERO_TRUE).max() < 0.02
    assert zs.solve([dict(p, camera=cam_bad) for p in poses], MARKER, REC)["verdict"] == "FAIL"  # the fixed-camera sim way


def test_gate_fails_closed(planned):
    poses = [exact_pose(p["q_deg"]) for p in planned["poses"]]
    few = zs.solve(poses[:11], MARKER, REC)
    assert few["verdict"] == "FAIL" and "need >= 12" in few["reasons"][0]
    rng = np.random.default_rng(1)
    noisy = [dict(p, corners=p["corners"] + rng.normal(0, 4.0, (4, 2)), std_px=4.0 * np.sqrt(9)) for p in poses]
    bad = zs.solve(noisy, MARKER, REC)
    assert bad["verdict"] == "FAIL" and any("px" in r or "sigma" in r for r in bad["reasons"])
    wrong = zm.Marker(MARKER.id, 30.0, MARKER.centre_mm, "+z", 90.0)  # print turned a quarter vs the model
    assert zs.solve(poses, wrong, REC)["verdict"] == "FAIL"


def render(folder, planned_poses, px_noise_gray=2.0, frames=6, seed=0):
    """Draw the base and gripper markers into blank images at each pose and write view-<pose>-<n>.png/.json."""
    rng = np.random.default_rng(seed)
    gen = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
    dic = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)

    def paste(canvas, mid, quad_px):
        src = np.pad(gen(dic, mid, 200), 40, constant_values=255)
        inner = np.float32([[40, 40], [240, 40], [240, 240], [40, 240]])
        canvas[:] = np.minimum(canvas, cv2.warpPerspective(src, cv2.getPerspectiveTransform(inner, np.float32(quad_px)),
                                                           (SIZE[0], SIZE[1]), borderValue=255))

    base_px = {i: zm.pixels(np.array(c) * 1000.0, REC, CAM) for i, c in BASE.items()}
    for k, p in enumerate(planned_poses):
        q = np.array(p["q_deg"])
        grip = zm.pixels(zm.marker_points_mm(q, ZERO_TRUE, MARKER), REC, CAM)
        for f in range(frames):
            img = np.full((SIZE[1], SIZE[0]), 255, np.uint8)
            for mid, quad in [*base_px.items(), (MARKER.id, grip)]:
                paste(img, mid, quad)
            noisy = np.clip(img + rng.normal(0, px_noise_gray, img.shape), 0, 255).astype(np.uint8)
            cv2.imwrite(str(folder / f"view-{k}-{f}.png"), noisy)
            (folder / f"view-{k}-{f}.json").write_text(json.dumps({"q": p["q_norm"], "unit": "norm"}))


def test_round_trip_through_files(tmp_path, planned):
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps({"schema": "x", "sites": {}, "cameras": {"top": REC}}))
    cap = tmp_path / "cap"
    cap.mkdir()
    render(cap, planned["poses"])
    before = sorted(p.name for p in cap.iterdir())
    argv = ["fit", "--calibration", str(cal), "--slot", str(SLOT), "--marker-size-mm", "30", "--marker-offset-mm", "45", "0", "12",
            "--capture", str(cap), "--report", str(tmp_path / "report.json")]
    rc = zc.main(argv)
    rep = json.loads((tmp_path / "report.json").read_text())
    assert sorted(p.name for p in cap.iterdir()) == before  # the capture is read-only to the tool
    assert rep["poses"] == 14 and rep["marker_noise_px"]["median_per_pose_std"] is not None
    # q_norm is rounded to 0.01 in the plan, so the drawn pose is the rounded one: the truth stays ZERO_TRUE
    assert np.abs(np.array(rep["zero_deg"]) - ZERO_TRUE).max() < 0.5, rep
    assert rc == (0 if rep["verdict"] == "PASS" else 2)


def test_failed_fit_writes_only_the_report(tmp_path, planned):
    cal = tmp_path / "cal.json"
    cal.write_text(json.dumps({"schema": "x", "sites": {}, "cameras": {"top": REC}}))
    cap = tmp_path / "cap"
    cap.mkdir()
    render(cap, planned["poses"][:8], frames=5)  # 8 poses: below the 12-pose gate
    rc = zc.main(["fit", "--calibration", str(cal), "--slot", str(SLOT), "--marker-offset-mm", "45", "0", "12",
                  "--capture", str(cap), "--report", str(tmp_path / "r.json")])
    assert rc == 2 and json.loads((tmp_path / "r.json").read_text())["verdict"] == "FAIL"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cal.json", "cap", "r.json"]
