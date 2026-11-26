"""Only an uninterrupted, actual checked grasp can contribute a USB recovery payload."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_recovery_cargo as cargo  # noqa: E402


@pytest.fixture
def grasp(tmp_path, monkeypatch):
    from cell_route_surface import contact_binding

    monkeypatch.setattr(cargo, "_pose", lambda *_: SimpleNamespace(x=0.15, y=0.1, z=0.045, yaw=0.0, tool_down_error_rad=0.0))
    config = {"arm_id": "arm_s", "io": str(tmp_path), "_fleet_task": "carry-19", "work_dir": str(tmp_path),
              "tcp_x_m": 0.074, "sites": {"board": {"surface_z": 0.03, "place": [0.15, 0.1], "yaw_deg": 0},
                                          "rack": {"layer": 2}}}
    cal = {"reference_top_sha256": "a" * 64, "reference_map_sha": "a" * 12, "reference_geometry_sha": "a" * 12}
    (tmp_path / "surface-board.json").write_text(json.dumps({
        "result": "touched", "site": "board", "xy": [0.15, 0.1], "touches_m": [0.0299, 0.0301], "surface_z": 0.03,
        "contact_binding": contact_binding(config, "board", cal, 0.074)}))
    entry = {"id": "box-2", "length_mm": 60, "width_mm": 30, "top_height_mm": 30, "mass_kg": 0.01}
    catalog = [entry, {**entry, "id": "box-1", "length_mm": 30}]
    target = {"object": {"object": entry["id"], "long_axis_deg": -80, "raw_m": [0.15, 0.1]}, "entry": entry,
              "pick": {"x": 0.15, "y": 0.1},
              "place": {"x": 0.16, "y": -0.12}}
    ack = {"operating_context": {"scope": "hardware", "session_id": "checked-07"},
           "library_sha256": "a" * 64, "t": 11.25, "command": "run grasp_pick", "ok": True,
           "holding": True, "state": [0.0] * 6}
    session = {"chunks": {"io": str(tmp_path)}, "started": 10.0, "ended": 12.0}
    return config, catalog, target, ack, cal, session


def _write(grasp, *following):
    config, catalog, target, ack, cal, session = grasp
    support = cargo._support(config, target, "board", cal)
    source_tier = {"object_id": "box-2", "site": "board", "source_tier": 1, "height_residual_mm": 0.5,
                   "surface": support, "top_sha256": "b"*64, "depth_sha256": "c"*64, "measured_top_mm": 30,
                   "stamp": 10.1}
    cargo.record_grasp(config, catalog, target, "board", "rack", ack, calibration=cal, source_tier=source_tier)
    rows = [ack, *[{**ack, "command": "state", "t": 11.5, **row} for row in following]]
    (Path(config["io"]) / "chunk-status.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    return cargo.interrupted_cargo(session, "arm_s")


def test_cargo_comes_from_grasped_entry_and_specific_destination(grasp):
    item = _write(grasp, {"command": "run lift_pick"})
    assert item["object_id"] == "box-2"
    assert item["grasp_above_base_m"] == pytest.approx(0.015)
    assert item["held_axis_deg"] == -80
    assert item["destination"] == "rack" and item["destination_layer"] == 2
    assert item["destination_xy_m"] == [0.16, -0.12]
    assert item["payload"]["object"] == item["object_id"] and item["task_id"] == "carry-19"
    assert item["catalog"] == grasp[1]
    assert cargo.interrupted_cargo(grasp[-1], "arm_b") is None
    assert cargo.interrupted_cargo({**grasp[-1], "started": 11.4}, "arm_s") is None


@pytest.mark.parametrize("row", [{"command": "run release_place"}, {"command": "run grasp_pick"},
                                {"holding": False}, {"operating_context": {"session_id": "next"}}])
def test_later_attempt_or_release_supersedes_the_grasp(grasp, row):
    assert _write(grasp, row) is None


def test_no_observed_grasp_no_identity(grasp):
    grasp[3]["holding"] = False
    assert _write(grasp) is None


def test_nonfleet_grasp_keeps_nominal_route_without_an_assigned_recovery_destination(grasp):
    del grasp[0]["_fleet_task"]
    item = _write(grasp)
    assert item["nominal_destination"] == {"site": "rack", "xy_m": [0.16, -0.12], "layer": 2}
    assert item["destination"] is None and item["destination_xy_m"] is None
    assert item["destination_layer"] is None and "task_id" not in item


def test_missing_or_corrupt_legacy_readback_and_offcentre_grasp(grasp):
    config, _, target, _, _, session = grasp
    target["object"]["grasp_shift_mm"] = 12
    assert _write(grasp) is None
    (Path(config["io"]) / cargo._FILE).write_text("{")
    assert cargo.interrupted_cargo(session, "arm_s") is None


@pytest.mark.parametrize("change", ["bias", "stack", "map", "xy", "estimated", "different_fk"])
def test_plausible_fk_cannot_substitute_for_matched_single_layer_source(grasp, change, monkeypatch):
    config, _, target, _, cal, _ = grasp
    if change == "bias":
        target["object"]["dz_m"] = 0.004
    elif change == "stack":
        config["sites"]["board"]["layers_below"] = 1
    elif change == "map":
        cal["reference_map_sha"] = "d" * 12
    elif change == "xy":
        target["pick"]["x"] += 0.01
    elif change == "different_fk":
        monkeypatch.setattr(cargo, "_pose", lambda *_: SimpleNamespace(x=0.16, y=0.1, z=0.045, yaw=0.0))
    else:
        (Path(config["work_dir"]) / "surface-board.json").unlink()
    assert _write(grasp) is None


@pytest.mark.parametrize("measured, expected", [(30.2, True), (34, False), (62.4, False)])
def test_depth_confirms_actual_object_base_against_calibrated_source_floor(grasp, monkeypatch, measured, expected):
    import cell_auto_pick_plan
    import cell_depth_slots
    import cell_route_check
    import cell_zone_verification as zones

    config, catalog, target, _, cal, _ = grasp
    now = cargo.time.time
    monkeypatch.setattr(cell_route_check, "source_floor", lambda *_: {"floor": [[1, 2, 9, 10]], "floor_depth_mm": [600]})
    monkeypatch.setattr(zones, "_depth_after", lambda *_: (object(), {"exposure_wall_estimate_s": now(), "raw_sha256": "c"*64}, None))
    monkeypatch.setattr(zones, "_frame", lambda *_, **kw: ({"image": object(), "source_stamp": now(),
                                                            "jpeg_sha256": "b"*64}, None))
    observed = {**target["object"], "hull_px": [[1, 2], [8, 2], [8, 9], [1, 9]]}
    monkeypatch.setattr(cell_auto_pick_plan, "observe", lambda *_, **kw: (None, None, [observed], None))
    def depth(_depth, _image, box, floor, tier, *, floor_depth_mm):
        assert box == (1, 2, 9, 10) and floor_depth_mm == [600] and tier == 1
        return {"ok": True, "occupied": True, "tier_ok": True, "tier": 1, "median_rel_mm": measured,
                "patch_offset_mm": 0.1, "plane_rms_mm": 0.2, "local_edge_px": 0.1}
    monkeypatch.setattr(cell_depth_slots, "depth_reference", depth)
    measured = cargo.source_base_tier(None, config, target, "board", cal, catalog, [1, 2, 16, 18])
    assert bool(measured) is expected
    if measured:
        assert measured["surface"]["min_z_m"] == 0.0299
        assert measured["surface"]["repeatability_m"] == pytest.approx(0.00015)
        assert measured["height_residual_mm"] == pytest.approx(0.5)
