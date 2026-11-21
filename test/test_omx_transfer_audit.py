import json
from pathlib import Path
import sys

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
from omx_transfer_audit import CAMERAS, RENDERS, audit, check_wrist_evidence, digest


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_transfer_audit_matches_cameras_and_handoff_without_site_acceptance(tmp_path):
    source = "1" * 40
    layout = "2" * 64
    cfg = dict(case="r08-v24-cad194", layers=1, seed=0, layout_sha256=layout)
    views, mujoco, captured = {}, {}, {}
    for index, name in enumerate(sorted(RENDERS)):
        for engine in ("isaac", "mujoco-source"):
            Image.new("RGB", (640, 480), (index, 0, 0)).save(tmp_path / f"{engine}-{name}.png")
        views[name] = dict(camera=f"/World/Cameras/{name}", resolution=[640, 480],
                           png_sha256=digest(tmp_path / f"isaac-{name}.png"))
        mujoco[name] = digest(tmp_path / f"mujoco-source-{name}.png")
    for name in ("omx-ab-cell.usd", "camera-comparison.png"):
        (tmp_path / name).write_text(name)
    for index, (name, role) in enumerate(CAMERAS.items()):
        photo = tmp_path / f"{role}.jpg"
        Image.new("RGB", (640, 480), (index, 0, 0)).save(photo)
        captured[role] = dict(source_stamp=100 + index * .01, sha256=digest(photo))
    usd = digest(tmp_path / "omx-ab-cell.usd")
    write_json(tmp_path / "geometry-check.json", dict(
        preset="v24-20261114-cad194", layout_sha256=layout, source_sha=source, usd_sha256=usd,
        camera_snapshot_sha256=None, mujoco_frame_sha256=mujoco))
    write_json(tmp_path / "comparison.json", dict(
        source_sha=source, camera_sha256=None, camera_comparison_sha256=digest(tmp_path / "camera-comparison.png"),
        isaac=dict(usd_sha256=usd, isaac_sdk="6.2.0.0", views=views),
        real_frames={name: captured[role]["sha256"] for name, role in CAMERAS.items()}))
    capture = write_json(tmp_path / "capture.json", dict(frames=captured))
    handoff_data = dict(stage_2_isaac=dict(ready=True, two_arm_config=cfg,
                                           two_arm_scenario="omx-map-container-stacking-rl"))
    handoff = write_json(tmp_path / "handoff.json", handoff_data)

    result = audit(tmp_path, capture, handoff)
    assert result["r2s"]["host_source_stamp_span_ms"] == 30
    assert result["r2s"]["pose_alignment"] == "unverified"
    assert result["r2s"]["wrist_alignment"] == {"status": "awaiting_holdouts"}
    assert result["s2r"]["physical_acceptance"] == "pending"
    assert result["isaac_physx"]["status"] == "not_run"

    for index, frame in enumerate(captured.values()):
        frame.update(exposure_monotonic_s=200 + index * .002, source_seq=index,
                     clock_semantics="v4l2_monotonic_start_of_exposure", boot_id="shared")
    write_json(capture, dict(frames=captured))
    sensor = audit(tmp_path, capture, handoff)["r2s"]
    assert sensor["sensor_exposure_span_ms"] == 6
    assert "host_source_stamp_span_ms" not in sensor
    captured["side"]["boot_id"] = "other"
    write_json(capture, dict(frames=captured))
    with pytest.raises(ValueError, match="V4L2 clock and boot"):
        audit(tmp_path, capture, handoff)
    captured["side"]["boot_id"] = "shared"
    joints = {
        arm: {
            key: dict(boot_id="shared", begin_monotonic_s=stamp, end_monotonic_s=stamp + .02,
                      motors=[dict(id=i, position_raw=2048, velocity_raw=1,
                                   hardware_error=0, torque_enabled=0) for i in range(11, 17)])
            for key, stamp in (("before", 199.96), ("after", 200.02))
        }
        for arm in ("arm_a", "arm_b")
    }
    write_json(capture, dict(frames=captured, joint_samples=joints))
    r2s = audit(tmp_path, capture, handoff)["r2s"]
    assert r2s["joint_observation"] == {"status": "stationary_bracket_verified", "max_window_ms": 80.0}
    assert r2s["pose_alignment"] == "unverified"
    joints["arm_b"]["after"]["begin_monotonic_s"] += 1200
    joints["arm_b"]["after"]["end_monotonic_s"] += 1200
    write_json(capture, dict(frames=captured, joint_samples=joints))
    with pytest.raises(ValueError, match="outside the camera capture window"):
        audit(tmp_path, capture, handoff)
    write_json(capture, dict(frames=captured))

    cfg["layout_sha256"] = "3" * 64
    write_json(handoff, handoff_data)
    with pytest.raises(ValueError, match="same CAD194 layout"):
        audit(tmp_path, capture, handoff)
    cfg["layout_sha256"] = layout
    write_json(handoff, handoff_data)
    (tmp_path / "isaac-side.png").write_text("tampered")
    with pytest.raises(ValueError, match="isaac-side.png"):
        audit(tmp_path, capture, handoff)


def test_wrist_requires_separate_holdouts_and_improvement_in_both_feature_types(tmp_path):
    point = dict(observed=[40, 100], baseline=[47, 100], candidate=[42, 100])
    other = dict(observed=[80, 110], baseline=[87, 110], candidate=[82, 110])
    row = dict(fit_capture_sha256="a" * 64, calibration_sha256="b" * 64,
               holdouts=[dict(capture_sha256=key * 64, jaw=[point, other], fixture=[point, other])
                         for key in "cd"])
    data = dict(schema="rosy.omx-wrist-holdout/1", layout_sha256="1" * 64,
                cameras={"a_wrist": row, "b_wrist": row})
    path = write_json(tmp_path / "wrist.json", data)
    evidence = check_wrist_evidence(path, data["layout_sha256"])
    assert (evidence["status"], evidence["provenance"]) == ("reported_improvement", "not_verified")

    row["holdouts"][1]["fixture"] = [dict(point, candidate=[57, 100]), other]
    write_json(path, data)
    assert check_wrist_evidence(path, data["layout_sha256"])["status"] == "rejected"

    row["holdouts"][1]["capture_sha256"] = row["fit_capture_sha256"]
    write_json(path, data)
    with pytest.raises(ValueError, match="independent holdouts"):
        check_wrist_evidence(path, data["layout_sha256"])
