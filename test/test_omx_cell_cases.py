"""Arm S cell problem cases become Isaac scenarios (deploy/robot/omx/cell_cases.py), and the suite
(deploy/robot/omx/cell_case_suite.py) says which still match the real outcome."""
import importlib.util
import json
import math
from pathlib import Path
import sys

import pytest

pytest.importorskip("yaml")
OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    def load(name):
        spec = importlib.util.spec_from_file_location(name, OMX / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    cases, suite_runner = load("cell_cases"), load("cell_case_suite")
finally:
    sys.path.remove(str(OMX))
F = cases.fixture()


def test_every_real_stop_is_either_a_valid_sim_case_or_names_the_test_that_covers_it():
    assert len(cases.REAL) == 6
    for case in cases.REAL:
        if "sim" in case:
            assert F.check_case(case["sim"]) == case["sim"]
        else:
            assert case["covered_by"].startswith("test/") and case["why_not_sim"]


def scene_row(box=(0.080, 0.100), outcome="empty", at=None, place="belt", t=1.0):
    return {"t": t, "from": "pinky", "to": "belt", "scene": {"box_m": list(box), "box_turn_deg": 4.0,
            "grasp_turn_deg": 4.0, "place": place, "outcome": outcome, "at": at}}


def test_a_pipeline_case_with_a_scene_becomes_a_case_relative_to_the_tray_centre():
    sim = cases.from_row(scene_row())["sim"]
    assert sim == {"box": [0.008, -0.006, 4.0], "place": "belt", "grasp_turn": 4.0, "expect": "not_held"}
    placing = cases.from_row(scene_row(outcome="contact", at="run descend_place", place=[0.072, 0.13]))["sim"]
    assert placing["expect"] == "frame_contact" and placing["place"] == [0.072, 0.13]
    assert cases.from_row(scene_row(outcome="misaligned"))["sim"]["expect"] is None  # measured, not judged


def test_rows_without_a_scene_or_off_the_isaac_tray_are_left_out_and_repeats_kept_once():
    assert cases.from_row({"t": 1, "facts": {}}) is None
    assert cases.from_row(scene_row(box=(0.20, 0.10))) is None
    suite = cases.suite([scene_row(t=1), scene_row(t=2)])
    assert len(suite) == len(cases.REAL) + 1


def fake_remote(statuses, report=None):
    """remote_isaac: check, then per start the listed statuses, then fetch with or without the report."""
    calls, queue = [], list(statuses)

    def call(action, *args):
        calls.append(action)
        if action == "check":
            return {"input_sha256": "ab" * 32}
        if action in ("start", "status"):
            status, error = queue.pop(0)
            return {"run_id": "r1", "status": status, "error": error}
        folder = Path(args[args.index("--receipt") + 1]).parent / "snap"
        folder.mkdir(exist_ok=True)
        if report:
            (folder / suite_runner.REPORT).write_text(json.dumps({"judgement": report}))
        return {"snapshot_directory": str(folder)}
    return call, calls


def test_a_busy_gpu_is_waited_out_and_the_judgement_compared_with_the_real_outcome(tmp_path):
    case = next(c for c in cases.REAL if c["id"].endswith("edge-over-pinky-frame"))
    call, calls = fake_remote([("QUEUED", None), ("FAILED", "admission_refused"), ("RUNNING", None),
                               ("SUCCEEDED", None)], report={"result": "frame_contact"})
    row = suite_runner.run_case(case, "f" * 40, tmp_path, sleep=lambda s: None, call=call)
    assert calls.count("start") == 2 and row["matches"] is True and row["status"] == "SUCCEEDED"


def test_a_run_without_a_published_report_fails_the_suite(tmp_path):
    """UNKNOWN (cleanup unconfirmed) publishes nothing: no judgement is not a pass."""
    case = next(c for c in cases.REAL if c["id"].endswith("site-yaw"))
    call, _ = fake_remote([("QUEUED", None), ("UNKNOWN", "owned cleanup or GPU release unconfirmed")])
    row = suite_runner.run_case(case, "f" * 40, tmp_path, sleep=lambda s: None, call=call)
    assert row["judgement"] is None and suite_runner.verdict([row]) == 1
    measured = dict(row, expect=None, judgement={"result": "held_not_placed"}, matches=None)
    assert suite_runner.verdict([measured]) == 0 and "measured" in suite_runner.table([measured], [])


def test_a_known_isaac_gap_is_reported_as_such_and_any_other_result_is_flagged(tmp_path):
    case = next(c for c in cases.REAL if c["id"].endswith("site-yaw"))
    assert case["isaac_gap"]["result"] == "held_not_placed"
    for result, matches, failing in (("held_not_placed", None, 0), ("placed", False, 1), ("not_held", True, 0)):
        call, _ = fake_remote([("QUEUED", None), ("SUCCEEDED", None)], report={"result": result})
        row = suite_runner.run_case(case, "f" * 40, tmp_path / result, sleep=lambda s: None, call=call)
        assert row["matches"] is matches and suite_runner.verdict([row]) == failing
    assert "known Isaac gap" in suite_runner.table([dict(row, known_gap="why", matches=None)], [])


def test_the_aim_sweep_measures_offsets_both_ways_along_and_across_the_jaws():
    sweep = cases.aim_sweep()
    assert len(sweep) == 1 + 2 * 2 * len(cases.AIM_MM) and len({c["id"] for c in sweep}) == len(sweep)
    for case in sweep:
        assert F.check_case(case["sim"]) == case["sim"] and case["sim"]["expect"] is None
    by_id = {c["id"]: c["sim"]["aim"] for c in sweep}
    assert by_id["aim-0mm"] == [0.0, 0.0]
    assert math.hypot(*by_id["aim-along+15mm"]) == pytest.approx(0.015, abs=1e-4)
    along, across = by_id["aim-along+10mm"], by_id["aim-across+10mm"]
    assert along[0] * across[0] + along[1] * across[1] == pytest.approx(0.0, abs=1e-6)  # perpendicular
    assert by_id["aim-along-5mm"] == [-v for v in by_id["aim-along+5mm"]]


def test_a_case_may_add_an_aim_but_only_a_small_finite_one():
    case = {"box": [0.0, 0.0, 0.0], "place": "belt", "grasp_turn": 0.0, "expect": None}
    assert F.check_case(case) == case  # no aim: the case is as before
    assert F.check_case(dict(case, aim=[0.005, 0])) == dict(case, aim=[0.005, 0.0])
    for bad in ([0.03, 0.0], [0.0], [float("nan"), 0.0], "0,0"):
        with pytest.raises(ValueError):
            F.check_case(dict(case, aim=bad))
