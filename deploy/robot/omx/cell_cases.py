#!/usr/bin/env python3
"""Arm S cell problem cases (D-872) as scenarios the simulators replay before the real arm repeats them.

Two sources: ``REAL``, the stops of the first real runs (docs/validation/omx-arm-s-real-cell-pipeline-2026-10-25),
and every row of the pipeline's ``cases.jsonl`` that carries a ``scene`` (box, jaw turn, place point, outcome).
A case the simulators cannot reproduce (bus timing, the jaws' mechanical end) names the test that covers it.
A sim case is the Isaac cell's case shape (``learning/envs/isaac/arm_s_cell_fixture.check_case``): the box
relative to the tray centre, the place point or the belt, the jaws' turn from the site yaw, and the outcome the
real cell saw, or None when the case only measures a candidate (the choices ledger compares those). A known
Isaac deviation (``isaac_gap``: the result Isaac gives instead, and why) is reported as a gap while Isaac gives
exactly that; any other result is flagged, better or worse, like test/known_failures.txt.

  cell_cases.py --cases ~/rosy-test/.../cell-pipeline/cases.jsonl --out suite.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from isaac_cell_frames import fixture  # noqa: E402

SCHEMA = "rosy.omx-cell-case-suite.v1"
EVIDENCE = "docs/validation/omx-arm-s-real-cell-pipeline-2026-10-25/result.md"
# what the real transfer reported, as the Isaac judgement names it; a contact while placing is the frame
OUTCOME = {"placed": "placed", "empty": "not_held"}

REAL = [
    {"id": "real-2026-10-25-1-stale-health-sample", "source": f"{EVIDENCE} stop 1",
     "covered_by": "test/test_omx_chunk_runner.py (HEALTH_PERIOD_S: health read once a second)",
     "why_not_sim": "bus timing of the real Dynamixel loop"},
    {"id": "real-2026-10-25-2-jaws-past-their-end", "source": f"{EVIDENCE} stop 2",
     "covered_by": "test/test_omx_chunk_runner.py, test/test_omx_cell_pipeline.py (grip clamp, grip_to)",
     "why_not_sim": "the follower jaws' mechanical end (48.5) is a property of the real gripper"},
    {"id": "real-2026-10-25-3-start-reference-off", "source": f"{EVIDENCE} stop 3",
     "sim": {"box": [0.02, -0.02, 0.0], "place": "belt", "grasp_turn": 0.0, "expect": "placed"}, "isaac_gap": {"result": "held_not_placed", "why": "Isaac's two effort-capped fingers let the box slide in the jaws (open: docs/validation/omx-arm-s-isaac-cell-2026-10-25)"},
     "note": "the box ~3 cm from the taught reference; the plan aims at the observed box"},
    {"id": "real-2026-10-25-4-edge-over-pinky-frame", "source": f"{EVIDENCE} stop 4",
     "sim": {"box": [0.0, 0.0, 0.0], "place": [0.072, 0.135], "grasp_turn": 0.0, "expect": "frame_contact"},
     "note": "a calibration point put the box's edge over the Pinky frame; the flat zone now refuses it"},
    {"id": "real-2026-10-25-5-turned-box-site-yaw", "source": f"{EVIDENCE} stop 5",
     "sim": {"box": [0.0, 0.0, 25.0], "place": "belt", "grasp_turn": 0.0, "expect": "not_held"}, "isaac_gap": {"result": "held_not_placed", "why": "Isaac's jaws grip a box turned 25 deg that the real jaws met on its corners, then let it slide (open: docs/validation/omx-arm-s-isaac-cell-2026-10-25)"},
     "note": "jaws at the site yaw on a box turned 25 degrees"},
    {"id": "real-2026-10-25-5-turned-box-capped-turn", "source": f"{EVIDENCE} stop 5",
     "sim": {"box": [0.0, 0.0, 25.0], "place": "belt", "grasp_turn": 10.0, "expect": None},
     "note": "the camera turn capped at 10 degrees: a candidate for the grasp_yaw choice, measured"},
]


def from_row(row: dict) -> dict | None:
    """A ``cases.jsonl`` row with a ``scene`` as a sim case, or None (no scene, or off the Isaac tray)."""
    scene = row.get("scene")
    if not scene:
        return None
    f = fixture()
    cx, cy = f.TRAY["center"]
    (bx, by), outcome = scene["box_m"], scene.get("outcome")
    expect = "frame_contact" if outcome == "contact" and str(scene.get("at", "")).endswith("place") else OUTCOME.get(outcome)
    sim = {"box": [round(bx - cx, 3), round(by - cy, 3), round(scene.get("box_turn_deg", 0.0), 1)],
           "place": "belt" if scene["place"] == "belt" else [round(v, 3) for v in scene["place"]],
           "grasp_turn": round(scene.get("grasp_turn_deg", 0.0), 1), "expect": expect}
    try:
        f.check_case(sim)
    except ValueError:
        return None
    return {"id": f"pipeline-{row.get('t')}-{row.get('from')}-{row.get('to')}", "source": "cases.jsonl", "sim": sim}


def suite(rows=()) -> list[dict]:
    """REAL and the replayable pipeline rows, one case per distinct scene (mm, 0.1 deg)."""
    out, seen = [], set()
    for case in [*REAL, *filter(None, map(from_row, rows))]:
        key = json.dumps(case.get("sim"), sort_keys=True) if "sim" in case else case["id"]
        if key not in seen:
            seen.add(key)
            out.append(case)
    return out


AIM_MM = (5, 10, 15)


def aim_sweep() -> list[dict]:
    """How far off the box the pick may aim and still hold it (2026-10-28): the coarse map is 10-15 mm off, the
    arm 2-3 mm on the descent, and the real tolerance is unmeasured. The nominal box, the pick aimed along the
    site's jaw yaw and across it by each of AIM_MM both ways; candidates (expect None), so the suite measures."""
    yaw = math.radians(fixture().BOX_YAW_DEG)
    cases = [{"id": "aim-0mm", "source": "aim sweep", "sim": {"box": [0.0, 0.0, 0.0], "place": "belt",
                                                               "grasp_turn": 0.0, "expect": None, "aim": [0.0, 0.0]}}]
    for axis, angle in (("along", yaw), ("across", yaw + math.pi / 2)):
        for mm in AIM_MM:
            for sign in (1, -1):
                d = sign * mm / 1000
                cases.append({"id": f"aim-{axis}{sign * mm:+d}mm", "source": "aim sweep",
                              "sim": {"box": [0.0, 0.0, 0.0], "place": "belt", "grasp_turn": 0.0, "expect": None,
                                      "aim": [round(d * math.cos(angle), 4), round(d * math.sin(angle), 4)]}})
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, action="append", default=[], help="a pipeline cases.jsonl")
    parser.add_argument("--aim-sweep", action="store_true", help="only the aim tolerance candidates (aim_sweep)")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    rows = [json.loads(line) for path in args.cases for line in path.read_text().splitlines() if line.strip()]
    cases = aim_sweep() if args.aim_sweep else suite(rows)
    args.out.write_text(json.dumps({"schema": SCHEMA, "cases": cases}, indent=1))
    print(json.dumps({"out": str(args.out), "cases": len(cases), "sim": sum("sim" in c for c in cases)}))


if __name__ == "__main__":
    main()
