"""A missing live view or failed Z16 capture cannot approve a physical tier."""

from __future__ import annotations

import os
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for root in (ROOT / "middleware/devices/omx/adapter", ROOT / "deploy/robot/omx"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from omx_adapter.z_profile import reconcile_top_and_side_z_mm  # noqa: E402
import cell_z_profile as czp  # noqa: E402
import cell_z_side_reference as zside  # noqa: E402
import cell_z_shuttle as shuttle  # noqa: E402


def test_depth_alignment_does_not_reuse_result_for_different_colour(monkeypatch):
    depth = np.ones((4, 4), dtype=np.uint16)
    colour = np.zeros((4, 4, 3), dtype=np.uint8)
    affine = np.array([[1, 0, 7], [0, 1, 9]], dtype=np.float32)
    monkeypatch.setattr(czp.cell_depth, "table_plane", lambda raw: None)
    monkeypatch.setattr(czp.cell_depth, "height_map", lambda raw, plane: raw.astype(float))
    monkeypatch.setattr(czp.cell_depth, "align_edges", lambda rgb, heights: (affine, 1.0))
    first = czp._aligned_depth_heights(depth)
    second = czp._aligned_depth_heights(depth, colour)
    assert np.array_equal(first[1], np.eye(3, dtype=np.float32)[:2])
    assert np.array_equal(second[1], affine)


def test_saved_z_profile_does_not_claim_independent_calibration(monkeypatch):
    depth = np.ones((4, 4), dtype=np.uint16)
    colour = np.zeros((4, 4, 3), dtype=np.uint8)
    monkeypatch.setattr(czp.cell_arm_cal, "load", lambda *a, **k: {})
    monkeypatch.setattr(czp.cell_arm_cal, "record_z_profile", lambda *a, **k: None)
    monkeypatch.setattr(czp, "_aligned_depth_heights", lambda *a, **k: (depth.astype(float), np.eye(3)[:2], 1.0))
    monkeypatch.setattr(czp.cell_depth, "plate_top", lambda *a, **k: 13.0)
    monkeypatch.setattr(czp.cell_depth, "height_at", lambda *a, **k: 30.0)
    profile = czp.calibrate_z_profile_mm({}, top_colour=colour, top_depth=depth,
                                         landmark_observations=[(300.0, 0.0), (275.0, 13.0)])
    assert profile["depth_plate_measured"] is True
    assert profile["measurement_calibrated"] is False


def test_fixed_side_reference_reports_pose_but_cannot_approve_height(monkeypatch):
    import cv2

    binding = {"viewer_label": "side", "role": "front", "focus_controls": {"focus_absolute": 15},
               "unique_hardware_identity": True, "viewer_invocation_id": "session-1",
               "producer_invocation_id": "producer-1"}
    monkeypatch.setattr(czp.cell_frame, "live_camera_binding", lambda camera, **kwargs: binding)
    side = np.zeros((480, 640, 3), dtype=np.uint8)
    intr = {"accepted": True, "camera": "side", "size": [640, 480], "K": [[600, 0, 320], [0, 600, 240], [0, 0, 1]],
            "dist": [0, 0, 0, 0, 0], "rms_px": 0.2,
            "board": {"cols": 7, "rows": 10, "square_m": 0.02, "marker_m": 0.015,
                      "dictionary": "DICT_4X4_50", "scale_bar_mm": 50.0},
            "source_frames": [{"file": f"{i}.jpg", "sha256": f"{i:064x}"} for i in range(25)],
            "device_binding": binding}
    world = [[[0, 0, 0], [15, 0, 0], [15, 0, 15], [0, 0, 15]],
             [[0, 0, 100], [15, 0, 100], [15, 0, 115], [0, 0, 115]]]
    R = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)
    config = {"intrinsics": intr, "markers": [{"id": 1, "corners_world_mm": world[0]},
                                                 {"id": 2, "corners_world_mm": world[1]}],
              "installed_pose": {"R": R.tolist(), "t_mm": [0, 0, 500]}}
    rvec = cv2.Rodrigues(R)[0]
    K = np.asarray(intr["K"], dtype=float)
    pixels = {marker_id: cv2.projectPoints(np.asarray(corners, dtype=float), rvec,
               np.array([0, 0, 500], dtype=float), K, np.zeros(5))[0].reshape(4, 2)
              for marker_id, corners in ((1, world[0]), (2, world[1]))}
    monkeypatch.setattr(zside, "_side_reference_markers", lambda frame: pixels)
    diagnostic = czp._fixed_side_reference_diagnostic(side, {"side_reference": config})
    assert diagnostic["fiducials_detected"] == [1, 2]
    assert diagnostic["reprojection_rms_px"] < 0.001
    assert diagnostic["pose_delta_mm"] < 0.001
    assert diagnostic["ok"] is False
    assert diagnostic["stack_plane_projection_verified"] is False
    assert diagnostic["three_height_gauge_verified"] is False

    monkeypatch.setattr(czp.cell_frame, "live_camera_binding", lambda camera, **kwargs: binding | {"focus_controls": {"focus_absolute": 16}})
    assert czp._fixed_side_reference_diagnostic(side, {"side_reference": config})["reason"] == "fixed side reference data invalid"
    monkeypatch.setattr(czp.cell_frame, "live_camera_binding", lambda camera, **kwargs: binding)

    missing = czp._fixed_side_reference_diagnostic(side, {"side_reference": config | {"markers": [config["markers"][0]]}})
    assert missing["ok"] is False
    assert missing["fiducials_detected"] == []


def test_failed_capture_never_reuses_old_raw(tmp_path, monkeypatch):
    dev, raw = tmp_path / "depth", tmp_path / "depth.raw"
    dev.touch()
    np.full((480, 640), 600, dtype=np.uint16).tofile(raw)
    os.utime(raw, (1, 1))

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("v4l2-ctl", 1)

    monkeypatch.setattr(czp.cell_depth.subprocess, "run", fail)
    assert czp.capture_top_depth_z16(str(dev), raw) is None
    monkeypatch.setattr(czp.cell_depth.subprocess, "run", lambda *a, **k: None)
    assert czp.capture_top_depth_z16(str(dev), raw) is None

    def failed_status(*args, **kwargs):
        np.full((480, 640), 610, dtype=np.uint16).tofile(raw)
        return subprocess.CompletedProcess(args[0], 1)

    monkeypatch.setattr(czp.cell_depth.subprocess, "run", failed_status)
    assert czp.capture_top_depth_z16(str(dev), raw) is None

    def fresh(*args, **kwargs):
        np.full((480, 640), 610, dtype=np.uint16).tofile(raw)

    monkeypatch.setattr(czp.cell_depth.subprocess, "run", fresh)
    captured = czp.capture_top_depth_z16(str(dev), raw)
    assert captured is not None and captured.shape == (480, 640) and int(captured[0, 0]) == 610


def test_depth_receipt_binds_raw_to_v4l2_start_of_exposure(tmp_path, monkeypatch):
    dev, raw = tmp_path / "depth", tmp_path / "depth.raw"
    dev.touch()

    def captured(cmd, **kwargs):
        assert "--verbose" in cmd and kwargs["stderr"] == subprocess.PIPE
        assert "--set-fmt-video=width=640,height=480,pixelformat=Z16" in cmd
        np.full((480, 640), 610, dtype=np.uint16).tofile(raw)
        stamp = time.monotonic()
        line = f"cap dqbuf: 0 seq: 12 bytesused: 614400 ts: {stamp:.6f} delta: 166.6 ms fps: 6.00 field: None (ts-monotonic, ts-src-soe)"
        return subprocess.CompletedProcess(cmd, 0, stderr=line)

    monkeypatch.setattr(czp.cell_depth.subprocess, "run", captured)
    depth, receipt = czp.cell_depth.capture_top_depth_z16_receipt(str(dev), raw)
    assert depth.shape == (480, 640) and receipt["source_seq"] == 12
    assert receipt["clock_semantics"] == "v4l2_monotonic_start_of_exposure"
    assert receipt["exposure_monotonic_s"] <= receipt["capture_ended_monotonic_s"]
    assert receipt["raw_sha256"] and receipt["valid_depth_ratio"] == 1.0
    uncertainty = receipt["wall_bridge_uncertainty_s"]
    assert receipt["capture_started_wall_s"] - uncertainty <= receipt["exposure_wall_estimate_s"] <= receipt["capture_ended_wall_s"] + uncertainty
    assert receipt["wall_bridge_uncertainty_s"] >= 0
    assert "boot_id" in receipt
    saved_receipt = raw.with_suffix(".raw.receipt.json")
    assert json.loads(saved_receipt.read_text())["raw_sha256"] == receipt["raw_sha256"]
    assert not raw.with_suffix(".raw.lock").exists()

    def no_source_stamp(cmd, **kwargs):
        row = captured(cmd, **kwargs)
        row.stderr = row.stderr.replace("ts-src-soe", "ts-src-eof")
        return row

    monkeypatch.setattr(czp.cell_depth.subprocess, "run", no_source_stamp)
    assert czp.cell_depth.capture_top_depth_z16_receipt(str(dev), raw) is None
    assert not raw.exists()
    assert not saved_receipt.exists()
    def failed_status(cmd, **kwargs):
        row = captured(cmd, **kwargs)
        row.returncode = 1
        return row

    monkeypatch.setattr(czp.cell_depth.subprocess, "run", failed_status)
    assert czp.cell_depth.capture_top_depth_z16_receipt(str(dev), raw) is None
    assert not raw.exists()
    monkeypatch.setattr(czp.cell_depth.subprocess, "run", captured)
    monkeypatch.setattr(czp.cell_depth, "_sync_parent", lambda *_: (_ for _ in ()).throw(OSError("sync failed")))
    assert czp.cell_depth.capture_top_depth_z16_receipt(str(dev), raw) is None
    assert not raw.exists() and not saved_receipt.exists()
    assert not raw.with_suffix(".raw.lock").exists()


def test_depth_receipt_refuses_concurrent_capture_of_same_path(tmp_path, monkeypatch):
    dev, raw = tmp_path / "depth", tmp_path / "depth.raw"
    dev.touch()
    raw.write_bytes(b"other capture")
    lock = raw.with_suffix(".raw.lock")
    lock.touch()
    monkeypatch.setattr(czp.cell_depth.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not capture")))
    assert czp.cell_depth.capture_top_depth_z16_receipt(str(dev), raw) is None
    assert raw.read_bytes() == b"other capture"


def test_one_view_and_uncalibrated_views_remain_unknown():
    assert reconcile_top_and_side_z_mm(None, 30.0)["aligned"] is False
    assert reconcile_top_and_side_z_mm(30.0, None)["dz_mm"] is None
    observed = {"found": True, "expected_tier": 1, "measured_top_z_mm": 30.0,
                "side_top_z_mm": 30.0, "valid_depth_ratio": 0.95,
                "measurement_calibrated": True}
    assert czp.evaluate_slot_spec_gate(observed)["verdict"] == "UNKNOWN"
    observed["depth_top_z_mm"] = 30.0
    observed["measurement_calibrated"] = False
    assert czp.evaluate_slot_spec_gate(observed)["verdict"] == "UNKNOWN"
    observed["measurement_calibrated"] = True
    assert czp.evaluate_slot_spec_gate(observed)["verdict"] == "PASS"
    assert czp.evaluate_slot_spec_gate(30.0)["verdict"] == "PASS"  # explicit numeric model evaluation


def test_saved_calibration_flag_is_not_current_frame_proof(monkeypatch):
    side = np.zeros((480, 640, 3), dtype=np.uint8)
    side[237:301, 232:288] = (30, 120, 240)
    depth = np.full((480, 640), 30, dtype=np.uint16)
    monkeypatch.setattr(czp, "_aligned_depth_heights", lambda *a, **k: (depth.astype(float), np.eye(3)[:2], 1.0))
    obs = czp.perceive_slot_z_mm(side, side, depth, col=2, z_profile={"measurement_calibrated": True})
    assert obs["found"] is True
    assert obs["measurement_calibrated"] is False
    assert obs["spec_gate"]["verdict"] == "UNKNOWN"


def test_synthetic_side_landmarks_cannot_prove_tier_even_with_depth(monkeypatch):
    side = np.zeros((480, 640, 3), dtype=np.uint8)
    side[251:315, 239:305] = (30, 120, 240)
    colour = np.zeros_like(side)
    depth = np.full((480, 640), 600, dtype=np.uint16)
    heights = np.full((480, 640), 30.0)
    affine = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    monkeypatch.setattr(czp, "_aligned_depth_heights", lambda *a, **k: (heights, affine, 1.0))
    monkeypatch.setattr(czp.cell_depth, "align_edges", lambda *a, **k: (affine, 1.0))
    monkeypatch.setattr(czp.cell_depth, "plate_top", lambda *a, **k: 13.0)
    monkeypatch.setattr(czp, "detect_side_self_profile_landmarks", lambda *a, **k: [(315.0, 0.0), (287.27, 13.0), (107.0, 97.5)])
    profile = czp.default_z_profile_mm()
    profile["measurement_calibrated"] = True
    profile["top_depth"].update({"measured_plate_top_mm": 13.0, "to_depth_matrix": affine.tolist(), "base_px": [120.0, 240.0]})
    obs = czp.perceive_slot_z_mm(side, colour, depth, col=2, tier=1, z_profile=profile)
    assert obs["measurement_calibrated"] is False
    assert obs["spec_gate"]["verdict"] == "UNKNOWN"
    assert obs["calibration_checks"]["depth_plate_mm"] == 13.0
    assert obs["calibration_checks"]["side_reference_verified"] is False

    profile["measurement_calibrated"] = False
    assert czp.perceive_slot_z_mm(side, colour, depth, col=2, tier=1, z_profile=profile)["spec_gate"]["verdict"] == "UNKNOWN"
    profile["measurement_calibrated"] = True
    assert czp.perceive_slot_z_mm(side, colour, None, col=2, tier=1, z_profile=profile)["spec_gate"]["verdict"] == "UNKNOWN"

    for changed in (None, [(330.0, 0.0), (302.27, 13.0), (122.0, 97.5)]):
        monkeypatch.setattr(czp, "detect_side_self_profile_landmarks", lambda *a, points=changed, **k: points or [])
        stale = czp.perceive_slot_z_mm(side, colour, depth, col=2, tier=1, z_profile=profile)
        assert stale["spec_gate"]["verdict"] == "UNKNOWN"
    monkeypatch.setattr(czp, "detect_side_self_profile_landmarks", lambda *a, **k: [(315.0, 0.0), (287.27, 13.0), (107.0, 97.5)])
    monkeypatch.setattr(czp.cell_depth, "plate_top", lambda *a, **k: 19.0)
    assert czp.perceive_slot_z_mm(side, colour, depth, col=2, tier=1, z_profile=profile)["spec_gate"]["verdict"] == "UNKNOWN"
    monkeypatch.setattr(czp.cell_depth, "plate_top", lambda *a, **k: 13.0)
    shifted = np.array([[1, 0, 5], [0, 1, 0]], dtype=np.float32)
    monkeypatch.setattr(czp.cell_depth, "align_edges", lambda *a, **k: (shifted, 1.0))
    assert czp.perceive_slot_z_mm(side, colour, depth, col=2, tier=1, z_profile=profile)["spec_gate"]["verdict"] == "UNKNOWN"


def test_live_missing_views_do_not_fall_back_to_sim_snapshot():
    audit = shuttle._audit_columns_for_spec_gate(side_img=np.zeros((480, 640, 3), dtype=np.uint8))
    assert audit["all_passed"] is False
    assert audit["flagged_columns"] == [1, 2, 3]
    assert all(v == "S5_VIEW_OR_GATE_MISMATCH" for v in audit["failure_codes"].values())


def test_physical_actuation_holds_before_first_leg_without_current_stack_proof(tmp_path):
    calls = []

    def act(step):
        calls.append(step)
        return {"result": "placed"}

    result = shuttle.execute_shuttle_roundtrip(work_dir=tmp_path, act_fn=act, snapshot_simulation=True)
    assert calls == []
    assert result["spec_gate_audit"]["all_passed"] is False
    assert result["leg1_result"]["result"] == "blocked_by_interlock"
    assert result["leg2_blocked_by_interlock"] is True

    stale_audits = {c: {"col": c, "basis": "side_view_and_top_depth", "found": True,
                         "expected_tier": 1, "measured_top_z_mm": 30.0,
                         "side_top_z_mm": 30.0, "depth_top_z_mm": 30.0,
                         "valid_depth_ratio": 0.95, "measurement_calibrated": True} for c in (1, 2, 3)}
    result = shuttle.execute_shuttle_roundtrip(work_dir=tmp_path, act_fn=act, column_audits=stale_audits)
    assert calls == []
    assert result["spec_gate_audit"]["all_passed"] is False


def test_snapshot_reference_requires_explicit_simulation_mode():
    assert shuttle._audit_columns_for_spec_gate()["failure_codes"] == {
        1: "S5_VIEW_OR_GATE_MISMATCH", 2: "S5_VIEW_OR_GATE_MISMATCH", 3: "S5_VIEW_OR_GATE_MISMATCH"}
    simulated = shuttle._audit_columns_for_spec_gate(snapshot_simulation=True)
    assert simulated["columns"][2]["verdict"] == "PASS"


def test_snapshot_replay_success_is_distinct_from_physical_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(shuttle, "_run_single_shuttle_leg", lambda *a, **k: {"result": "placed", "task_verified": False})
    replay = shuttle.execute_shuttle_roundtrip(col=2, work_dir=tmp_path, snapshot_simulation=True)
    assert replay["simulated_success"] is True
    assert replay["completed"] is False

    monkeypatch.setattr(shuttle, "execute_shuttle_roundtrip", lambda **k: replay)
    checked = shuttle.run_snapshot_verification(work_dir=tmp_path)
    assert checked["verified"] is True
    assert checked["schema"] == "rosy.omx-snapshot-simulation-verification.v1"
    assert checked["verification_scope"] == "offline_snapshot_simulation"
    assert checked["physical_task_verified"] is False


def test_nine_safe_plans_with_held_sample_are_not_completed(tmp_path):
    result = shuttle.execute_temp_plate_123_tier_recovery_loop(work_dir=tmp_path, dry_run=False)
    assert result["shuttle_count"] == 9
    assert result["all_wrist_rolls_safe"] is True
    assert result["sample_roundtrip"]["leg1_result"]["result"] == "blocked_by_interlock"
    assert result["verified_shuttle_count"] == 0
    assert result["completed"] is False and result["ok"] is False
    assert result["completion_verdict"] == "UNKNOWN"
    assert result["all_z_aligned"] is False


def test_live_side_only_is_unknown_but_measured_disagreement_fails():
    side_only = {"col": 1, "basis": "side_view_profile", "found": True,
                 "expected_tier": 1, "measured_top_z_mm": 30.0,
                 "side_top_z_mm": 30.0, "measurement_calibrated": False}
    audit = shuttle._audit_columns_for_spec_gate(column_audits={1: side_only})
    assert audit["columns"][1]["verdict"] == "UNKNOWN"
    assert audit["columns"][1]["failure_code"] == "S5_VIEW_OR_GATE_MISMATCH"
    mismatch = {**side_only, "depth_top_z_mm": 45.0, "measurement_calibrated": True,
                "valid_depth_ratio": 0.95}
    audit = shuttle._audit_columns_for_spec_gate(column_audits={1: mismatch})
    assert audit["columns"][1]["verdict"] == "FAIL"
    assert audit["columns"][1]["failure_code"] == "S2_TOPPLED_OR_SLUMPED"
