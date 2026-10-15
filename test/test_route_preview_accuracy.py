"""D-767 7 route preview scorer (tools/sim/route_preview_accuracy.py) on synthetic truth."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "sim" / "route_preview_accuracy.py"


def _mod():
    spec = importlib.util.spec_from_file_location("route_preview_accuracy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drive(error=0.0, phantom=False, drop=False):
    """A robot at 0.1 m/s from path 0 for 20 s; J1 at path 1.0, the crosswalk near edge at 1.5 (a bend B9 at 1.2
    that is not there with ``phantom``). A prediction every 1 s lists what is still ahead, ``at_m`` off by ``error``."""
    truth = [{"robot_id": "r", "t": float(t), "path_m": 0.1 * t} for t in range(31)]
    truth += [{"robot_id": "r", "t": 10.0, "pass": {"kind": "turn", "id": "J1"}},
              {"robot_id": "r", "t": 15.0, "pass": {"kind": "crosswalk", "id": "cw"}}]
    places = [(1.0, "turn", "J1", {})] + ([] if drop else [(1.5, "crosswalk", None, {"zone_id": "cw"})])
    places += [(1.2, "bend", "B9", {})] if phantom else []
    preds = []
    for t in range(20):
        here = 0.1 * t
        events = [{"s_m": s, "at_m": round(s - here + error, 3), "kind": kind, "place_id": place, "params": params}
                  for s, kind, place, params in sorted(places) if s - here > 1e-9]
        events.append({"s_m": 2.5, "at_m": 2.5 - here, "kind": "authority_end", "place_id": None, "params": {}})
        preds.append({"robot_id": "r", "t": t + 100.0, "pose_stamp": float(t), "leg_id": "L", "horizon_m": 2.0,
                      "front_d_m": here, "events": events})
    return preds, truth


def test_an_exact_preview_passes():
    preds, truth = _drive()
    result = _mod().score(preds, truth)
    assert result["pass"] and result["scored"] == 25 and result["p95_error_m"] == pytest.approx(0.0, abs=1e-9)
    assert result["missed"] == 0 and result["phantom"] == 0


def test_the_bound_grows_with_distance_and_differs_per_profile():
    mod = _mod()
    preds, truth = _drive(error=0.06)                 # 0.03 + 0.05 x at_m < 0.06 near the place
    assert not mod.score(preds, truth)["pass"]
    assert mod.score(preds, truth, "device")["pass"]  # 0.10 + 0.05 x at_m
    assert mod.score(*_drive(error=0.02), "gazebo")["pass"]


def test_missed_and_phantom_events_fail():
    mod = _mod()
    missed = mod.score(*_drive(drop=True))
    assert missed["missed"] == 15 and missed["missed_rate"] > 0.01 and not missed["pass"]
    phantom = mod.score(*_drive(phantom=True))
    assert phantom["phantom"] == 12 and not phantom["pass"]


def test_main_reads_json_lines_and_exits_by_the_verdict(tmp_path, capsys):
    preds, truth = _drive()
    for name, rows in (("p.jsonl", preds), ("t.jsonl", truth)):
        (tmp_path / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert _mod().main([str(tmp_path / "p.jsonl"), str(tmp_path / "t.jsonl"), "--clock", "pose_stamp"]) == 0
    assert json.loads(capsys.readouterr().out)["pass"] is True
