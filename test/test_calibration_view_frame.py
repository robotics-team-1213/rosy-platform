"""Reference binding and projection of calibration-view evidence."""
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_attempts
import cell_params
import cell_calibration_view as view


def test_register_exact_served_frame_and_refuse_large_shift(tmp_path, monkeypatch):
    other = tmp_path / "service-cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    ref_img = np.random.default_rng(51).integers(0, 256, (240, 320), dtype=np.uint8)
    def jpeg(image):
        return cv2.imencode(".jpg", image)[1].tobytes()
    ref = jpeg(ref_img)
    (tmp_path / "ref.jpg").write_bytes(ref)
    cal = {"sites": {}, "reference_top_sha256": hashlib.sha256(ref).hexdigest(),
           "reference_map_sha": cell_attempts.digest({}), "reference_geometry_sha": cell_attempts.digest({})}
    cal_path = tmp_path / "cal.json"
    cal_path.write_text(json.dumps(cal))
    cfg = tmp_path / "cfg.json"
    (tmp_path / "cell-params-stack.json").write_text(json.dumps({"schema": cell_params.SCHEMA, "params": {}}))
    cfg.write_text(json.dumps({"calibration_path": str(cal_path), "params_path": "cell-params-stack.json", "sites": {},
                               "preflight": {"reference_top": str(tmp_path / "ref.jpg")}}))
    entry = {"config_path": str(cfg)}
    assert view.bind_frame(entry, "reference", ref)[1]["status"] == "reference"
    shifted = jpeg(np.roll(ref_img, 2, axis=1))
    corrected, receipt = view.bind_frame(entry, "live", shifted)
    assert receipt["status"] == "aligned" and 1 <= receipt["max_px"] <= 5
    assert receipt["reference_sha256"] == cal["reference_top_sha256"]
    def mae(raw):
        actual = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        return np.mean(np.abs(actual[:, 8:-8].astype(float) - ref_img[:, 8:-8]))
    assert mae(corrected) < mae(shifted) / 2
    displaced = jpeg(np.roll(ref_img, 30, axis=1))
    unchanged, rejected = view.bind_frame(entry, "live", displaced)
    assert unchanged == displaced and rejected["status"] == "unverified"
    assert view.bind_frame(entry, "reference", shifted)[1]["status"] == "unverified"


def test_planned_visits_are_evidence_not_jaw_proximity():
    h = [[0.001, 0, 0], [0, 0.001, 0], [0, 0, 1]]
    record = {"homography": h, "points": [{"pixel": [10, 20], "arm_m": [0.01, 0.02]}], "z_view": 0.1}
    plans = [[0.01, 0.02], [0.03, 0.04]]
    legacy = view._build_map_detail(record, plans, {}, 0.0)
    assert [p["status"] for p in legacy["planned_points"]] == ["unmatched", "unmatched"]
    record["planned_visits"] = [{"point": plans[0], "pixel": [12, 20], "status": "observed"},
                                {"point": plans[1], "status": "missed"}]
    actual = view._build_map_detail(record, plans, {}, 0.0)["planned_points"]
    assert [p["status"] for p in actual] == ["observed", "missed"]
    assert actual[0]["observed_pixel"] == [12, 20]
    # The camera centre in arm coordinates is not the optical axis of the approximate overhead model.
    record["camera_in_base"] = {"t": [0.10, 0.10, 0.50]}
    assert view._project_point(record, {}, [0.20, 0.10], 0.0)["pixel_surface_z"] == [180, 100]
