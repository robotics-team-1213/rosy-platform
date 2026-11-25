"""Camera check results distinguish displaced images from untrusted map generations."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_calibrate
import cell_diagnose
import cell_pipeline
import cell_post_eval
import cell_upkeep_checks


@pytest.mark.parametrize(("evidence", "refusal", "issue"), [
    ({"camera_shift": {"ok": True, "max_px": 18.0}}, True, "camera_moved"),
    ({"camera_shift": {"ok": True, "max_px": 2.5},
      "map_binding_error": "top camera map site geometry changed"}, True, "camera_map_binding"),
    ({"camera_shift": {"ok": True, "max_px": 18.0}, "reference_mismatch": True}, True, "camera_map_binding"),
    ({"camera_shift": {"ok": False, "why": "no features"}}, True, "camera_shift_unmeasured"),
    ({"no_reference": True, "map_binding_error": "top camera map reference changed"}, True, "camera_reference_missing"),
    ({"no_reference": True}, False, "camera_reference_missing"),
    ({"camera_shift": {"ok": True, "max_px": 6.0}}, False, None),
])
def test_physical_image_evidence_and_refusal(evidence, refusal, issue):
    result = cell_diagnose.camera_reference(evidence, 6.0)
    assert result["camera_moved"] is refusal
    assert result["camera_issue"] == issue
    assert result["max_shift_px"] == 6.0
    if issue == "camera_reference_missing":
        assert cell_calibrate.stale(result) == ["review-camera-reference"]


@pytest.mark.parametrize("saved", [
    {"sites": {"old": {"homography": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}}},
    {"sites": {}, "reference_geometry_sha": "stale"},
    {"sites": {}, "schema": "unknown"},
    {"sites": {}},
])
def test_only_pristine_first_commissioning_can_remap_missing_maps(tmp_path, saved):
    import numpy as np

    config = {"preflight": {"reference_top": str(tmp_path / "absent.jpg")},
              "calibration_path": str(tmp_path / "arm.json"), "sites": {"new": {"surface_z": 0.01}},
              "calibrate": {"map_sites": ["new"]}}
    found = cell_calibrate.check(config, saved, [], np.zeros((32, 32, 3), np.uint8))
    assert found["missing_map"] == ["new"] and found["camera_moved"]
    if saved == {"sites": {}}:
        assert found["initial_commissioning"] and cell_calibrate.stale(found)[:2] == ["remap", "regions"]
    else:
        assert cell_calibrate.stale(found) == ["review-camera-reference"]


def test_matching_images_with_stale_geometry_hold_all_automated_recovery(tmp_path, monkeypatch, capsys):
    evidence = {"camera_shift": {"ok": True, "max_px": 2.5}, "map_binding_error": "top camera map site geometry changed"}
    found = {**evidence, **cell_diagnose.camera_reference(evidence, 6.0), "missing_map": ["one_partial_site"]}
    config = {"plan_path": str(tmp_path / "plan.json"), "work_dir": str(tmp_path), "io": str(tmp_path),
              "calibration_path": str(tmp_path / "map.json"), "cameras": {}, "sites": {}}
    (tmp_path / "plan.json").write_text("{}")
    path = tmp_path / "cell.json"
    path.write_text(json.dumps(config))
    cell = SimpleNamespace(frame=lambda name: object())
    monkeypatch.setattr(cell_pipeline, "FifoCell", lambda *args: cell)
    monkeypatch.setattr(cell_calibrate, "check", lambda *args: found)
    assert cell_calibrate.main(["--config", str(path), "check"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["todo"] == ["review-camera-reference"]
    assert report["check"]["camera_advice"] == cell_diagnose.ASK["camera_map_binding"]
    assert cell_calibrate.main(["--config", str(path), "auto", "--commissioning", "--person-at-switch",
                                "--only", "remap", "regions", "--verify"]) == 2
    assert json.loads(capsys.readouterr().out)["held"] == report["check"]["camera_advice"]
    post = cell_post_eval.run_post_eval(cell, config, {}, commissioning=True, person_at_switch=True)
    assert post["verdict"] == "escalate" and post["reason"] == "camera_map_binding"
    assert post["todo"] == report["todo"]
    io = SimpleNamespace(calibrate=lambda *args: report, decode=lambda image: image)
    upkeep = cell_upkeep_checks.check_map(config, {}, b"image", io)
    assert upkeep["motion"] is False and upkeep["found"]["map_binding_error"] == evidence["map_binding_error"]
    assert "commissioning" not in upkeep["detail"]
