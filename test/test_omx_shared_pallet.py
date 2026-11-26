"""Fixture registration compares only matching physical work surfaces, independently of the robot frame."""
from pathlib import Path
import json
import sys

import cv2
import numpy as np

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    from cell_shared_pallet import compare_surfaces, shared_pallet
finally:
    sys.path.remove(str(OMX))


def test_same_scene_with_shifted_work_surface_is_not_camera_drift():
    image = np.random.default_rng(9).integers(0, 256, (340, 420), dtype=np.uint8)
    source_quad = np.float32([[145, 105], [260, 108], [256, 238], [139, 234]])
    shift = np.float32([[1, 0, 8], [0, 1, -3]])
    target = cv2.warpAffine(image, shift, (420, 340))
    aligned = source_quad + [8, -3]
    # Same surface, different first vertex and opposite winding.
    result = compare_surfaces(image, target, source_quad, np.float32(np.roll(aligned[::-1], 1, axis=0)), 15)
    assert result["status"] == "consistent" and max(result["corner_error_px"]) < 1.0
    wrong = np.float32(aligned - [29, 0])
    result = compare_surfaces(image, target, source_quad, wrong, 15)
    assert result["status"] == "mismatch" and min(result["corner_error_px"]) > 28
    assert max(result["corner_error_px"]) < 30
    assert np.allclose(result["peer_surface_in_frame_px"], aligned, atol=1)
    border = compare_surfaces(image, target, source_quad, np.float32(aligned - [15, 0]), 15)
    assert border["status"] == "near_tolerance"


def test_other_camera_or_unrelated_work_surface_is_not_compared(tmp_path):
    peer_path = tmp_path / "peer.json"
    a = {"arm_id": "arm_a", "zone_peer": "arm_b", "sites": {"pallet": {}}, "cameras": {"top": {"url": "cam1"}}}
    b = {**a, "arm_id": "arm_b", "zone_peer": "arm_a", "cameras": {"top": {"url": "cam2"}}}
    peer_path.write_text(json.dumps(b))
    assert shared_pallet(a, {}, peer_path=peer_path)["status"] == "not_applicable"
    b.update(cameras=a["cameras"], sites={"temp_plate_b": {}})
    peer_path.write_text(json.dumps(b))
    assert shared_pallet(a, {}, peer_path=peer_path)["status"] == "not_applicable"


def test_remap_mismatch_preserves_existing_generation(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(OMX))
    import cell_calibrate as cc
    import io
    import types
    import cell_hooks
    import cell_shared_pallet

    img = np.zeros((48, 64, 3), np.uint8)
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    path = tmp_path / "config.json"
    cal = tmp_path / "cal.json"
    cal.write_text('{"sites":{}}')
    import cv2
    ref = tmp_path / "ref.jpg"
    cv2.imwrite(str(ref), img)
    config = {"arm_id": "arm_a", "plan_path": str(plan), "cameras": {}, "sites": {"pallet": {}},
              "work_dir": str(tmp_path), "io": str(tmp_path), "calibration_path": str(cal),
              "preflight": {"reference_top": str(ref)}}
    path.write_text(json.dumps(config))
    files = {p: p.read_bytes() for p in (path, cal, ref)}
    fake = types.SimpleNamespace(frame=lambda *_: img)
    monkeypatch.setitem(sys.modules, "cell_pipeline", types.SimpleNamespace(FifoCell=lambda *_: fake))
    monkeypatch.setattr(cc, "check", lambda *_: {"map_binding_error": None})
    monkeypatch.setattr(cc, "stale", lambda *_: ["remap"])
    monkeypatch.setattr(cc.rp, "plan", lambda *_: [])
    monkeypatch.setattr(cc.rp, "refusal", lambda *_: None)
    monkeypatch.setattr(cell_hooks, "stills", lambda *_: io.BytesIO())
    monkeypatch.setattr(cc, "remap", lambda *a, **kw: {"loo_error_mm": {"max": 1.0}})
    monkeypatch.setattr(cc, "map_agrees", lambda *_: True)
    monkeypatch.setattr(cc, "move_regions", lambda *_: None)
    monkeypatch.setattr(cell_shared_pallet, "shared_pallet", lambda *a, **kw: {"status": "mismatch"})
    assert cc.main(["--config", str(path), "auto", "--only", "remap", "--commissioning", "--person-at-switch"]) == 2
    assert "shared pallet work surfaces disagree" in capsys.readouterr().out
    assert all(p.read_bytes() == content for p, content in files.items())
