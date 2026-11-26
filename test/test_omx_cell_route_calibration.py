"""The commissioning report reuses evidence without changing the executable route or auto-step gates."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for module in ("deploy/robot/omx", "middleware/devices/omx/adapter"):
    sys.path.insert(0, str(ROOT / module))

import cell_calibrate
from cell_route_calibration import route_calibration_report
from cell_route_check import route_check


SRC, DST = "tmp-a-1-l1", "ship-h1r0-l0"


def setup_route(tmp_path):
    cfg = {"arm_id": "arm_a", "work_dir": str(tmp_path), "sites": {
        "table": {}, "tmp-a-1": {"map_from": "table"}, SRC: {"tier_of": "tmp-a-1", "layer": 1},
        DST: {"map_from": "table", "layer": 0, "place": [0.08, 0.12], "surface_z": 0.01}},
        "zone_rois": {"top": {"tmp-a-1": [90, 380, 137, 477], "ship-h1r0": [300, 180, 340, 282]},
                      "floor": [[210, 80, 260, 100]], "floor_depth_mm": [585]}}
    calibration = {"sites": {"table": {"homography": [[0.001, 0, 0], [0, 0.001, 0], [0, 0, 1]],
                                       "loo_error_mm": {"max": 1}}}}
    checks = {"map_binding_error": None, "camera_shift": {"ok": True, "max_px": 0.8}, "max_shift_px": 6.0}
    return cfg, calibration, checks


def test_completed_floor_registration_drops_only_its_gap(tmp_path):
    cfg, cal, checks = setup_route(tmp_path)
    initial = route_calibration_report(cfg, cal, checks, SRC, DST)
    evidence = initial["calibration_evidence"]
    src = evidence["sites"]["source"]
    assert src["map"]["current"] and src["map"]["map_site"] == "table"
    assert src["xy_m"] is None and src["surface_z_m"] is None
    floor_gap = {"role": "source", "site": SRC, "action": "record_depth_floor_reference"}
    assert floor_gap in evidence["gaps"]
    cfg["sites"][SRC]["zone_rois"] = {"floor": [[70, 330, 120, 349]], "floor_depth_mm": [591]}
    snapshot = deepcopy((cfg, cal, checks))
    updated = route_calibration_report(cfg, cal, checks, SRC, DST)
    assert updated == route_calibration_report(cfg, cal, checks, SRC, DST)
    assert snapshot == (cfg, cal, checks)
    assert list(tmp_path.iterdir()) == []
    added = updated.pop("calibration_evidence")
    assert updated == route_check(cfg, SRC, DST)
    assert not updated["depth_inputs_configured"]
    assert added["gaps"] == [gap for gap in evidence["gaps"] if gap != floor_gap]
    assert added["sites"]["source"]["floor_reference"]["optical_depth_mm"] == [591]
    assert added["sites"]["destination"]["floor_reference"]["optical_depth_mm"] == [585]
    assert added["scene"]["status"] == "not_sampled"
    assert cell_calibrate.stale(checks) == cell_calibrate.stale({**checks, "route": updated})


def test_shift_and_conflicting_alias_prevent_current_evidence(tmp_path):
    cfg, cal, checks = setup_route(tmp_path)
    checks.update(camera_moved=True, camera_issue="camera_moved", camera_shift={"ok": True, "max_px": 18.1})
    cal["sites"][SRC] = {**cal["sites"]["table"], "z_view": 0.12}
    report = route_calibration_report(cfg, cal, checks, SRC, DST)["calibration_evidence"]
    assert not report["reference_current"]
    assert report["gaps"][0]["action"] == "check_camera_map_reference"
    assert report["sites"]["source"]["map"]["reason"] == "different_parent_map"
    assert report["sites"]["destination"]["map"]["reason"] == "reference_not_current"
    assert not report["sites"]["destination"]["contact_current"]
    assert report["sites"]["destination"]["surface_z_m"] == 0.01


def test_existing_area_maps_survive_four_missing_named_endpoints(tmp_path):
    points = [{"pixel": [100 + 8 * i, 180 + i * i], "arm_m": [0.08 + 0.003 * i, 0.06 + 0.002 * i]}
              for i in range(10)]
    record = {"points": points, "z_view": 0.125, "loo_error_mm": {"max": 2.4}}
    checks = {"map_binding_error": None, "camera_shift": {"ok": True, "max_px": 0}, "max_shift_px": 6.0}
    for arm, source, destination in (("arm_a", SRC, DST), ("arm_b", "tmp-b-2-l1", "ship-h1r2-l0")):
        area = "temp_plate_" + arm[-1]
        cfg = {"arm_id": arm, "work_dir": str(tmp_path), "sites": {area: {}, "pallet": {}}}
        cal = {"sites": {area: record, "pallet": deepcopy(record)}}
        report = route_calibration_report(cfg, cal, checks, source, destination)
        assert not report["depth_inputs_configured"]
        evidence = report["calibration_evidence"]
        for role, expected in (("source", area), ("destination", "pallet")):
            site = evidence["sites"][role]
            historical = site["area_map_candidate"]
            assert historical["area_map_site"] == expected
            assert historical["sites_with_same_points"] == sorted([area, "pallet"])
            assert historical["point_count"] == 10 and historical["z_view_m"] == 0.125
            assert historical["loo_error_mm"] == {"max": 2.4}
            assert not site["map"]["current"] and site["xy_status"] == "missing"
            assert site["surface_z_m"] is None and site["floor_reference"] is None
            actions = [gap["action"] for gap in evidence["gaps"] if gap.get("role") == role]
            assert "verify_named_site_on_existing_map" in actions and "validate_site_map" not in actions
            assert "measure_named_xy" in actions and "verify_surface_contact" not in actions


def test_complete_static_inputs_continue_to_fresh_preflight_without_repeat_visits(tmp_path, monkeypatch):
    cfg, cal, checks = setup_route(tmp_path)
    cfg["sites"][SRC].update(place=[0.11, -0.18], surface_z=0.007,
                             zone_rois={"floor": [[75, 330, 120, 349]], "floor_depth_mm": [580]})
    # The independent visit verifier owns the pixel/FK replay. Here check how its result directs the planner.
    import cell_route_calibration as planner
    monkeypatch.setattr(planner, "exact_visit", lambda *args: {"verified": False, "verified_at_visit_height": True})
    result = route_calibration_report(cfg, cal, checks, SRC, DST)
    evidence = result["calibration_evidence"]
    assert result["depth_inputs_configured"] and evidence["gaps_are_advisory"]
    assert evidence["next_machine_action"] == "continue_to_existing_fresh_preflight"
    assert evidence["sites"]["source"]["visit_at_height_current"]
    assert not evidence["sites"]["source"]["support_xy_current"]
    assert "verify_named_xy" not in {gap["action"] for gap in evidence["gaps"]}


def cad_row():
    return {"center_px": [100.5, 400], "capture_sha256": "a" * 64, "holdout_sha256": "b" * 64,
            "camera_reference_sha256": "c" * 64, "holdout_max_px": 2.25}


def test_cad_observation_is_only_an_image_diagnostic(tmp_path):
    cfg, cal, checks = setup_route(tmp_path)
    cal["reference_top_sha256"] = "c" * 64
    before = route_calibration_report(cfg, cal, checks, SRC, DST)
    row = cad_row()
    cal["cad_image_observations"] = {"tmp-a-1": row}
    after = route_calibration_report(cfg, cal, checks, SRC, DST)
    obs = after["calibration_evidence"]["sites"]["source"].pop("cad_image_observation")
    assert obs == {**row, "status": "recorded_image_only", "next": "verify_arm_base_registration"}
    assert before == after


@pytest.mark.parametrize(("change", "status"), [
    ({"capture_sha256": "short"}, "invalid"), ({"holdout_sha256": "A" * 64}, "invalid"),
    ({"camera_reference_sha256": "e" * 64}, "stale"), ({"holdout_max_px": float("nan")}, "invalid"),
    ({"holdout_max_px": -1}, "invalid"), ({"holdout_max_px": True}, "invalid"),
    ({"center_px": [137, 400]}, "invalid"), ({"center_px": [100, 477]}, "invalid"),
    ({"center_px": [True, 400]}, "invalid"), ({"center_px": [100]}, "invalid"),
    ({"xy_m": [0.1, 0.2]}, "invalid"),
])
def test_cad_bad_observation_does_not_clear_route_gaps(tmp_path, change, status):
    cfg, cal, checks = setup_route(tmp_path)
    cal["reference_top_sha256"] = "c" * 64
    before = route_calibration_report(cfg, cal, checks, SRC, DST)
    cal["cad_image_observations"] = {"tmp-a-1": {**cad_row(), **change}}
    after = route_calibration_report(cfg, cal, checks, SRC, DST)
    assert after["calibration_evidence"]["sites"]["source"].pop("cad_image_observation")["status"] == status
    assert after == before


def test_cad_observation_requires_current_camera_and_named_roi(tmp_path):
    cfg, cal, checks = setup_route(tmp_path)
    cal.update(reference_top_sha256="c" * 64, cad_image_observations={"tmp-a-1": cad_row()})
    def source():
        return route_calibration_report(cfg, cal, checks, SRC, DST)["calibration_evidence"]["sites"]["source"]
    checks["camera_moved"] = True
    assert source()["cad_image_observation"]["status"] == "stale"
    checks["camera_moved"] = False
    del cfg["zone_rois"]["top"]["tmp-a-1"]
    assert source()["cad_image_observation"]["reason"] == "center_not_in_named_roi"
