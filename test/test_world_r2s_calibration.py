"""Tests for photo-grounded Real-to-Sim (R2S) palette, birdview plane, and camera calibration."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tools" / "sim", ROOT / "applications" / "world"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bridge_real_fleet  # noqa: E402
import build_bundle  # noqa: E402
import record_mujoco  # noqa: E402
import serve  # noqa: E402
import world_env_adapter  # noqa: E402
import world_r2s_calibrate as r2s  # noqa: E402
import world_training_hooks as hooks  # noqa: E402


def test_sample_photo_palette_extracts_rois(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()

    bv = np.zeros((200, 400, 3), dtype=np.uint8)
    bv[:, :] = (104, 107, 113)  # #686b71 floor mat
    bv[90:100, 120:220] = (154, 114, 129)  # #9a7281 pink guide
    bv[15:50, 115:125] = (49, 79, 74)  # #314f4a green bay
    Image.fromarray(bv).save(data / "site-birdview.jpg", quality=99)

    cp = np.zeros((200, 200, 3), dtype=np.uint8)
    cp[:, :] = (86, 92, 91)
    cp[5:30, 10:45] = (208, 156, 25)  # #d09c19 yellow worktable
    cp[128:152, 94:118] = (152, 206, 236)  # #98ceec ship sky
    cp[82:110, 104:116] = (235, 119, 51)  # #eb7733 orange cargo
    Image.fromarray(cp).save(data / "cell-photo.jpg", quality=99)

    pal = r2s.sample_photo_palette(data)
    assert pal["wall_white_hex"] == "#e6eaef"
    assert abs(int(pal["floor_mat_hex"][1:3], 16) - 104) <= 4
    assert abs(int(pal["worktable_yellow_hex"][1:3], 16) - 208) <= 6


def test_calibrate_birdview_plane_recovers_metric_extents(tmp_path: Path) -> None:
    # Build synthetic 1040x560 birdview at 400 px/m with exact [-1.29, -0.71, 1.31, 0.69] m bounds.
    px_per_m = 400.0
    x0, y1 = -1.29, 0.69
    w, h = 1040, 560
    img = np.full((h, w, 3), 106, dtype=np.uint8)

    bar_y = int(round((y1 - r2s.CANONICAL_PINK_BAR_Y_M) * px_per_m))
    img[bar_y - 3:bar_y + 4, int(0.28 * w):int(0.55 * w)] = (160, 110, 130)
    for xm in r2s.CANONICAL_PINK_STRIPES_X_M:
        xp = int(round((xm - x0) * px_per_m))
        img[bar_y - 110:bar_y - 16, xp - 3:xp + 4] = (160, 110, 130)

    path = tmp_path / "site-birdview.jpg"
    Image.fromarray(img).save(path, quality=98)
    cal = r2s.calibrate_birdview_plane(path)
    assert cal["calibrated"] is True
    assert abs(cal["px_per_m"] - px_per_m) < 4.0
    assert cal["pink_stripe_residual_rms_mm"] < 2.0
    assert abs(cal["plane"][0] - x0) < 0.02
    assert abs(cal["plane"][3] - y1) < 0.02


def test_transform_d435_and_build_r2s_calibration(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (tmp_path / "manifest.json").write_text(json.dumps({
        "field_photo": {
            "bundle_path": "data/field-photo.jpg",
            "plane": [-1.37, -0.76, 1.37, 0.76, 400.0],
            "calibration_revision": "paint-test",
            "captured_at": "2026-11-23T15:12:42+00:00",
        },
    }), encoding="utf-8")
    (data / "site-registration.json").write_text(json.dumps({
        "errors": [{"id": "c1", "error_m": 0.0001}],
        "site_from_cell": {"yaw_rad": -math.pi / 2, "translation_m": [0.793, 0.355, 0.0]},
    }), encoding="utf-8")
    (data / "geometry.json").write_text(json.dumps({
        "preset": "v24-20261114-cad194",
        "plate_inner_gap_mm": 194.0,
    }), encoding="utf-8")

    out_path = r2s.write_r2s_calibration(tmp_path, update_sums=True)
    assert out_path.is_file()
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert doc["schema"] == "rosy.world.r2s-calibration.v1"
    assert doc["geometry_audit"]["canonical_plate_inner_gap_mm"] == 194.0
    assert doc["geometry_audit"]["arm_ab_span_mm"] == 336.5
    assert doc["geometry_audit"]["measured_plate_inner_gap_mm"] == 189.8
    assert doc["geometry_audit"]["plate_gap_delta_mm"] == -4.2
    assert doc["arm_bases_site"]["arm_a"]["pose_m"] == [0.62625, 0.278, 0.084]
    assert doc["arm_bases_site"]["arm_b"]["pose_m"] == [0.96275, 0.278, 0.084]
    assert doc["map_gate"]["available"] is True
    assert doc["map_gate"]["ok"] is True
    assert "d435_top" in doc["cameras"]
    site_eye = doc["cameras"]["d435_top"]["site_frame"]["eye"]
    assert abs(site_eye[0] - (0.793 + 0.0869)) < 1e-4
    assert (tmp_path / "SHA256SUMS.txt").is_file()


def test_real_fleet_estop_and_summary_propagate_through_serve(tmp_path: Path) -> None:
    sha = "a" * 64
    fleet_payload = {
        "robots": [
            {
                "robot_id": "rosy_45",
                "online": True,
                "state": {
                    "pose": {"x": 0.745, "y": -0.207, "yaw": -1.57},
                    "battery": {"percent": 82},
                    "safety": {"estop": True},
                },
            },
            {
                "robot_id": "arm_a",
                "online": True,
                "state": {
                    "joints": [0.0, -1.0, 0.7, 0.3, 0.0, 0.0],
                    "safety": {"estop": False},
                },
            },
        ],
    }
    snap = bridge_real_fleet.fleet_state_to_world_state(fleet_payload, site_map_sha256=sha, now_ms=10_000)
    assert snap is not None
    assert snap["safety"] == {"estop": True, "estop_all": False, "estop_robots": ["rosy_45"]}
    assert snap["fleet_summary"] == {"online": 2, "total": 6}

    fleet_payload["robots"][0]["state"]["safety"]["estop"] = False
    snap_clear = bridge_real_fleet.fleet_state_to_world_state(fleet_payload, site_map_sha256=sha, now_ms=10_000)
    assert snap_clear is not None
    assert snap_clear["safety"] == {"estop": False, "estop_all": False, "estop_robots": []}

    bundle = tmp_path / "bundle"
    (bundle / "data" / "worlds").mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({
        "inputs": {"site-map/world_261026_v7_active.json": {"sha256": sha}},
    }), encoding="utf-8")
    (bundle / "data" / "worlds" / "real-site.json").write_text(json.dumps(snap), encoding="utf-8")

    discovered = serve.discover_worlds(bundle, now_ms=10_500)
    real_entry = next(w for w in discovered["worlds"] if w["world_id"] == "real-site")
    assert real_entry["safety"]["estop"] is True
    assert real_entry["safety"]["estop_robots"] == ["rosy_45"]
    assert real_entry["fleet_summary"] == {"online": 2, "total": 6}


def test_record_mujoco_resolves_canonical_site_map_sha(tmp_path: Path) -> None:
    manifest_sha = "b" * 64
    bundle = tmp_path / "bundle"
    (bundle / "data").mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps({
        "inputs": {"site-map/world_261026_v7_active.json": {"sha256": manifest_sha}},
    }), encoding="utf-8")
    assert record_mujoco._resolve_site_map_sha256(None, bundle / "data" / "mujoco-top.jpg", ROOT) == manifest_sha
    assert record_mujoco._resolve_site_map_sha256("C" * 64, bundle / "data" / "mujoco-top.jpg", ROOT) == "c" * 64
    fallback_sha = record_mujoco._resolve_site_map_sha256(None, tmp_path / "other" / "mujoco-top.jpg", ROOT)
    assert len(fallback_sha) == 64
    assert fallback_sha != "0" * 64


def test_build_bundle_auto_emits_r2s_calibration_and_sums(tmp_path: Path) -> None:
    import io

    inputs = tmp_path / "inputs"
    top_buf = io.BytesIO()
    Image.new("RGB", (64, 64), (208, 156, 25)).save(top_buf, format="JPEG", quality=90)
    entries = {
        "site-map/world_261026_v7_active.json": json.dumps({"version": 1, "map": {"schema": "rosy.site_map/1", "map_id": "world_261026", "places": [], "edges": []}}).encode("utf-8"),
        "site-map/world_261026_v7_map.png": b"\x89PNG\r\n\x1a\n",
        "isaac/geometry-check.json": json.dumps({"preset": "v24-20261114-cad194", "plate_inner_gap_mm": 194.0}).encode("utf-8"),
        "isaac/calibration/check.json": json.dumps({"ok": True}).encode("utf-8"),
        "isaac/isaac-overview.png": b"\x89PNG\r\n\x1a\n",
        "isaac/calibration/frames/top.jpg": top_buf.getvalue(),
        "equipment/site-registration.json": json.dumps({
            "errors": [{"id": "c1", "error_m": 0.0001}],
            "site_from_cell": {"yaw_rad": -math.pi / 2, "translation_m": [0.793, 0.355, 0.0]},
        }).encode("utf-8"),
    }
    sums_lines = []
    for rel, raw in entries.items():
        target = inputs / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        sums_lines.append(f"{hashlib.sha256(raw).hexdigest()}  {rel}")
    (inputs / "SHA256SUMS.txt").write_text("\n".join(sums_lines) + "\n", encoding="utf-8")

    out = build_bundle.build(inputs, tmp_path / "bundle-out", recording=None)
    cal_path = out / "data" / "r2s-calibration.json"
    assert cal_path.is_file()
    cal = json.loads(cal_path.read_text(encoding="utf-8"))
    assert cal["geometry_audit"]["canonical_plate_inner_gap_mm"] == 194.0
    assert cal["arm_bases_site"]["arm_a"]["pose_m"] == [0.62625, 0.278, 0.084]
    sums_text = (out / "SHA256SUMS.txt").read_text(encoding="utf-8")
    cal_digest = hashlib.sha256(cal_path.read_bytes()).hexdigest()
    assert f"{cal_digest}  data/r2s-calibration.json" in sums_text


def test_mujoco_two_arm_hook_emits_total_slots_27_for_three_hold_layout(tmp_path: Path) -> None:
    parity_in = hooks.canonical_parity_inputs(ROOT)
    worlds_dir = tmp_path / "worlds"

    class _FakeLayout:
        ship_cells = {f"ship-h{h}r{r}-l{l}": {} for h in (1, 2, 3) for r in range(3) for l in range(3)}

        def containers(self):
            return [("bar-1", None)]

    class _FakeWorld:
        q = {"arm_a": slice(0, 6), "arm_b": slice(6, 12)}
        layout = _FakeLayout()

        def pose(self, _data, _cid):
            return np.array([0.05, -0.02, 0.09]), 0.0, 0.0

    class _FakeData:
        qpos = np.zeros(12, dtype=float)

    mj_hook = world_env_adapter.TrainingWorldHook(
        world_id="mujoco-9x3x3-01",
        backend="mujoco",
        run_id="mujoco-9x3x3-01",
        site_map_sha256=parity_in["site_map_sha256"],
        worlds_dir=worlds_dir,
        cargo_tray=parity_in["cargo_tray"],
        min_interval_s=0.0,
    )
    cb = hooks.make_mujoco_two_arm_hook(
        _FakeWorld(), mj_hook, reg=parity_in["site_from_cell"], task_name="stack", episode_ref=[1],
    )
    cb(_FakeData(), "arm_a:place")
    snap = json.loads((worlds_dir / "mujoco-9x3x3-01.json").read_text(encoding="utf-8"))
    assert snap["cell_ab"]["total_slots"] == 27
