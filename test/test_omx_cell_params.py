"""cell_params (rosy.omx-cell-params.v1): validation, defaults equal the shipped constants, modules honour a value,
attempt and decision rows name the parameters they ran with, auto pick refuses a site without a surface height."""
import copy
import json
from pathlib import Path
import sys

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_attempts
    import cell_auto_pick as auto
    import cell_objects
    import cell_params as prm
    import cell_pivot
    import chunk_runner
    import judge_seat
finally:
    sys.path.remove(str(OMX))

EXAMPLE = OMX / "cell-params.example.json"


def file_with(tmp_path, **changes):
    data = json.loads(EXAMPLE.read_text())
    for name, change in changes.items():
        data["params"][name.replace("__", ".")] = dict(data["params"][name.replace("__", ".")], **change)
    path = tmp_path / "params.json"
    path.write_text(json.dumps(data))
    return path


@pytest.mark.parametrize("change,message", [
    ({"unit": "px"}, "unit"), ({"value": "25"}, "number"), ({"value": True}, "number"), ({"value": 0}, "outside"),
    ({"value": 500}, "outside"), ({"source": "guess"}, "source"), ({"evidence": " "}, "evidence")])
def test_a_bad_unit_type_range_source_or_evidence_is_refused(tmp_path, change, message):
    with pytest.raises(ValueError, match=message):
        prm.load(file_with(tmp_path, objects__chroma=change))


def test_a_count_must_be_an_integer_and_an_unknown_name_is_refused(tmp_path):
    with pytest.raises(ValueError, match="integer"):
        prm.load(file_with(tmp_path, runner__contact_ticks={"value": 2.5}))
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"schema": prm.SCHEMA, "params": {"objects.nope": {}}}))
    with pytest.raises(ValueError, match="unknown"):
        prm.load(path)


def test_defaults_equal_the_constants_the_modules_shipped_with_and_the_example_file():
    shipped = {"objects.chroma": 25.0, "objects.light": 60.0, "objects.min_px": 150, "objects.split_fill": 0.8,
               "objects.split_axis_deg": 12.0, "pivot.still_px": 40, "pivot.diff_px": 30, "pivot.min_blob": 300,
               "pivot.max_blob": 90, "pivot.follow_px": 60, "pivot.agree_px": 3.0, "pivot.bias_reach_mm": 80.0,
               "pivot.grip_closed": 50.5, "auto.temp_stop_c": 55, "auto.pwm_fraction": 0.8, "auto.approach_near_m": 0.020,
               "auto.grasp_depth_m": 0.015, "auto.clear_mm": 55.0, "auto.finger_mm": 8.0, "auto.closing_theory_deg": 90,
               "auto.closing_alt_deg": 0, "runner.pace_lag": 1.6, "runner.pace_rise": 0.3, "runner.pace_max_s": 3.0,
               "runner.idle_park_s": 180.0, "runner.idle_stop_s": 180.0, "runner.contact_lag": 1.5, "runner.contact_ticks": 2}
    assert {k: prm.default(k) for k in shipped} == shipped
    assert (cell_objects.CHROMA, cell_objects.LIGHT, cell_objects.MIN_PX) == (25.0, 60.0, 150)
    assert (cell_pivot.STILL_PX, cell_pivot.BIAS_REACH_MM) == (40, 80.0)
    assert (auto.TEMP_STOP_C, auto.PWM_FRACTION) == (55, 0.8)
    assert (chunk_runner.PACE_LAG, chunk_runner.IDLE_PARK_S, chunk_runner.CONTACT_TICKS) == (1.6, 180.0, 2)
    assert prm.load(EXAMPLE) == prm.load() and prm.load()["sha"] == prm.digest(prm.load()["values"])


def test_a_value_in_the_file_changes_the_sha_and_the_foreground(tmp_path):
    loaded = prm.load(file_with(tmp_path, objects__chroma={"value": 90.0}))
    assert loaded["sha"] != prm.load()["sha"] and loaded["values"]["objects.chroma"] == 90.0
    img = np.full((60, 60, 3), (200, 200, 200), np.uint8)
    img[20:40, 20:40] = (160, 200, 160)  # a faint green patch
    assert cell_objects.foreground(img, (0, 0, 60, 60)).any()
    strict = dict(loaded["values"], **{"objects.open_px": 25})
    assert not cell_objects.foreground(img, (0, 0, 60, 60), params=strict).any()  # a 20 px patch dies in a 25 px opening
    white = np.full((60, 60, 3), 120, np.uint8)
    white[20:40, 20:40] = 250  # a white floor line: lightness only
    assert cell_objects.foreground(white, (0, 0, 60, 60)).any()
    assert not cell_objects.foreground(white, (0, 0, 60, 60), params={"objects.light": 255.0}).any()
    board = np.full((60, 60, 3), 120, np.uint8)
    board[:, 50:] = (60, 140, 220)  # an orange board right of the floor
    assert cell_objects.foreground(board, (0, 0, 60, 60)).any()
    assert not cell_objects.foreground(board, (0, 0, 60, 60), surface_px=[(0, 0), (48, 0), (48, 60), (0, 60)]).any()



def test_attempt_and_decision_rows_name_the_parameters_they_ran_with(tmp_path, monkeypatch):
    monkeypatch.setattr(cell_attempts, "RUN", dict(cell_attempts.RUN))
    cell_attempts.start(tmp_path / "a.jsonl", "r")
    assert cell_attempts.context({}, {}, "pinky")["params_sha"] == prm.load()["sha"]
    path = file_with(tmp_path, runner__pace_lag={"value": 2.0})
    cell_attempts.start(tmp_path / "a.jsonl", "r", params=str(path))
    assert cell_attempts.context({}, {}, "pinky")["params_sha"] == prm.load(path)["sha"] != prm.load()["sha"]
    rows = []
    seat = judge_seat.Seat(lambda *a: {"decision": "retry", "reason": "x"}, log=rows.append, params=str(path))
    seat.decide({"box_found": True, "next": "grasp", "aligned": False})
    assert rows[0]["params_sha"] == prm.load(path)["sha"]


def test_a_site_given_only_its_surface_as_z_is_never_planned_at_the_surface(tmp_path):
    config = json.loads((OMX / "cell-pipeline.example.json").read_text())
    config["sites"]["floor"] = {"z": 0.006, "yaw_deg": 0.0}  # the surface itself, no surface_z
    with pytest.raises(SystemExit, match="surface_z"):
        auto.surface_z(config, "floor")
    config["sites"]["floor"]["surface_z"] = 0.006  # z at the surface: the fingers would hit the floor
    with pytest.raises(SystemExit, match="below"):
        auto.surface_z(config, "floor")
    config["sites"]["floor"]["z"] = 0.021
    assert auto.surface_z(config, "floor") == 0.006
    config["params"] = prm.load()["values"] | {"auto.grasp_depth_m": 0.02}
    with pytest.raises(SystemExit, match="below"):
        auto.surface_z(config, "floor")
