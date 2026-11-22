"""omx_real2sim.diff's arm bases, TCP and twin gap rows, on the committed snapshot and on twin/dr_next files built with the real writers' shapes."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sim"))
import omx_map_gate as map_gate  # noqa: E402
import omx_real2sim as r2s  # noqa: E402
import omx_real2sim_findings as fnd  # noqa: E402
import omx_twin_helpers as helpers  # noqa: E402
import omx_two_arm_sites as sites  # noqa: E402

CAD194 = "v24-20261114-cad194"
CAD190 = "v24-20261114-cad190"
SNAP = ROOT / "deploy/robot/omx/sim/cell_snapshots/20261112-1838.json"


def snapshot():
    return json.loads(SNAP.read_text(encoding="utf-8"))


def view(px, dx=0., dy=0.):  # the writer's own summary, so the keys are the real ones
    return helpers.summarise_views([dict(t=0., top=dict(px=px, dx=dx, dy=dy, score=2.))])


def twin_file(tmp_path, name, views, lag=None):
    d = tmp_path / name
    d.mkdir()
    (d / "twin.json").write_text(json.dumps(dict(episode=name, view=views, tracking=lag and dict(real_lag_s=lag))))
    return d


def test_the_planner_tcp_is_the_one_the_compiler_defaults_to():
    src = (ROOT / "deploy/robot/omx/cell_directive_compiler.py").read_text(encoding="utf-8")
    assert 'resolve_tcp(exec_cfg.get("tcp_x_m"), plan.get("tcp_x_m"))' in src


def test_cad194_bases_are_compared_only_in_their_own_frame():
    got = fnd.arm_bases(CAD194, snapshot())
    assert got["frame"] == map_gate.PHOTO_1114 and got["inner_gap_mm"] == pytest.approx(194.0, abs=.1)
    a = got["against"]
    assert a["docks-photo"]["comparable"] and a["docks-photo"]["inner_gap_mm"] == pytest.approx(189.8, abs=.1)
    assert a["docks-photo"]["delta_mm"]["arm_a"] == pytest.approx(2.1, abs=.2)   # 168.25 vs 166.15 mm from the centreline
    assert a["docks-photo"]["within_tolerance"] is True
    assert a["photo-20261114"]["comparable"] and a["photo-20261114"]["delta_mm"] == {"arm_a": 0.2, "arm_b": 4.2}  # the by-eye pick: arm_a agrees, arm_b is 4.2 mm (past the 3 mm tolerance) from the 194 plan
    assert a["photo-20261114"]["within_tolerance"] is False
    for stale in ("plate-centre", "snapshot"):  # the 11-03 survey frame: never subtracted from a table-edge map
        assert a[stale]["comparable"] is False and "delta_mm" not in a[stale]


def test_cad190_is_the_dl52_gap_and_agrees_with_the_photo_reading_within_a_millimetre():
    got = fnd.arm_bases(CAD190, snapshot())
    assert got["frame"] == map_gate.PHOTO_1114 and got["inner_gap_mm"] == pytest.approx(190.0, abs=.1)
    a = got["against"]
    assert a["docks-photo"]["delta_mm"]["arm_a"] == pytest.approx(0.1, abs=.1)  # 166.25 vs 166.15 mm from the centreline
    assert a["cad-190"]["delta_mm"] == {"arm_a": 0.0, "arm_b": 0.0} and a["cad-194"]["inner_gap_mm"] == pytest.approx(194.0, abs=.1)
    assert a["docks-photo"]["within_tolerance"] and a["cad-194"]["within_tolerance"]


def test_the_default_layout_compares_the_snapshot_in_the_survey_frame():
    default = fnd.arm_bases(None, snapshot())
    assert default["frame"] is None and default["against"]["snapshot"]["comparable"] is False  # measured-194 default is unmeasured
    got = fnd.arm_bases(None, snapshot(), arm_bases="surveyed")
    assert got["frame"] == map_gate.FIXTURE
    assert got["against"]["snapshot"]["comparable"] and got["against"]["snapshot"]["delta_mm"]["arm_b"] > 3
    assert got["against"]["snapshot"]["within_tolerance"] is False  # arm_b FK .153 vs plate centre .164: G-21


def test_tcp_names_the_planner_sim_gap_and_the_sweeps_kept_values():
    t = fnd.tcp()
    assert t["planner_minus_sim_mm"] == pytest.approx(14.5, abs=.1) and "sweep_kept_m" not in t
    assert fnd.tcp(dr_next=dict(tcp_m=[.074]))["planner_kept"] is False
    assert fnd.tcp(dr_next=dict(tcp_m=[.074, .0885]))["planner_kept"] is True


def test_dr_next_rows_follow_the_sweep_writers_shape(tmp_path):
    import omx_carry_sweep
    dr = dict(tcp_m=[.074], sag_mm=[4.0], zero_deg=[0., 2.], physics={"design": 1.}, vision_frac=.34)
    assert set(dr) == set(omx_carry_sweep.DR)  # what ingest writes to dr_next.json
    rows = fnd.dr_rows(dr, "dr_next.json")
    assert [(r["id"], r["item"], r["status"]) for r in rows] == [("G-22", "tcp.dr_next", "candidate")]
    assert fnd.dr_rows(dict(dr, tcp_m=[.074, .0885])) == []
    with pytest.raises(SystemExit):
        fnd.dr_rows(dict(vision_frac=.3))


def test_twin_rows_flag_only_cameras_past_their_limit_and_servo_lag_that_differs_by_joint(tmp_path):
    ok, bad = twin_file(tmp_path, "e1", view(1.5)), twin_file(tmp_path, "e2", view(10.8, 0., 6.), lag=[.10, .20, .34, .15, .12])
    assert fnd.twin_rows(ok) == []
    rows = fnd.twin_rows(tmp_path)
    assert {r["id"]: r for r in rows}.keys() == {"G-19", "G-23"}
    g19 = next(r for r in rows if r["id"] == "G-19")
    assert g19["item"] == "view.top" and g19["limit"] == 3 and g19["value"]["episodes"] == ["e2"] and g19["value"]["median_dy"] == 6
    assert fnd.twin_rows(twin_file(tmp_path, "e3", view(1.), lag=[.16] * 5)) == []


def test_diff_report_lists_arm_bases_tcp_and_the_twin_rows(tmp_path):
    d = twin_file(tmp_path, "e2", view(10.8))
    dr = tmp_path / "dr_next.json"
    dr.write_text(json.dumps(dict(tcp_m=[.074], zero_deg=[0., 2.], physics={}, vision_frac=.34)))
    out = r2s.diff_report(snapshot(), snapshot(), CAD194, d, dr)
    assert out["changed"] == {} and out["rerun"] == []
    assert out["arm_bases"]["preset"] == CAD194 and out["tcp"]["planner_kept"] is False
    assert out["gaps"] == ["G-19", "G-22"] and [r["id"] for r in out["gap_rows"]] == ["G-19", "G-22"]
    assert "gap_rows" in json.loads(json.dumps(out))


def test_measure_refuses_a_preset_whose_frame_is_not_the_previous_snapshots(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    (tmp_path / "frames").mkdir()
    cv2.imwrite(str(tmp_path / "frames/top.jpg"), np.zeros((480, 640, 3), np.uint8))
    prev = json.loads(SNAP.read_text(encoding="utf-8"))
    prev["frame"] = map_gate.FIXTURE
    p = tmp_path / "prev.json"
    p.write_text(json.dumps(prev))
    with pytest.raises(SystemExit, match="not one map"):
        r2s.measure(tmp_path, p, preset=CAD194)


def test_diff_report_does_not_double_the_rows_a_snapshot_already_carries(tmp_path):
    d = twin_file(tmp_path, "e2", view(10.8))
    new = dict(snapshot(), gap_rows=fnd.twin_rows(d))
    out = r2s.diff_report(snapshot(), new, CAD194, d)
    assert [r["id"] for r in out["gap_rows"]] == ["G-19"]
