import json
from pathlib import Path
import sys

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/sim"))
from omx_transfer_audit import CAMERAS, RENDERS, audit, digest


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
    assert result["s2r"]["physical_acceptance"] == "pending"
    assert result["isaac_physx"]["status"] == "not_run"

    cfg["layout_sha256"] = "3" * 64
    write_json(handoff, handoff_data)
    with pytest.raises(ValueError, match="same CAD194 layout"):
        audit(tmp_path, capture, handoff)
    cfg["layout_sha256"] = layout
    write_json(handoff, handoff_data)
    (tmp_path / "isaac-side.png").write_text("tampered")
    with pytest.raises(ValueError, match="isaac-side.png"):
        audit(tmp_path, capture, handoff)
