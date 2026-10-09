"""Read-only camera boundary counterexample; this is candidate evidence, not GT."""

import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "tools/perception_prototype/realrun"),
                str(ROOT / "middleware/perception"), str(ROOT / "contracts/foundation")]
from replay import (BevVO, CENTRE_KW, FPS, GROUND, VIDEO, X_OFF,  # noqa: E402
                    comp_stats, wall_mask)
from control.sensing.perception.lane_boundaries import LaneBoundaryTracker  # noqa: E402


def run(part, start, end, *, visual_odom=False):
    cap = cv2.VideoCapture(VIDEO % part)
    assert cap.isOpened(), VIDEO % part
    if not visual_odom:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
    tracker = LaneBoundaryTracker(camera_x_offset_m=X_OFF)
    vo = BevVO() if visual_odom else None
    result = None
    for index in range(0 if visual_odom else start, end + 1):
        ok, frame = cap.read()
        assert ok, (part, index)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        wall, _ = wall_mask(gray)
        pose = vo.step(gray, wall) if vo else (0.0, 0.0, 0.0)
        if index < start and not visual_odom:
            continue
        observation = tracker.update(index / FPS, pose, frame, GROUND, **CENTRE_KW)
        if index != end:
            continue
        view = tracker._view
        selected = {}
        paint = tracker.last.get("paint")
        if paint is not None:
            _, labels = cv2.connectedComponents(paint, connectivity=4)
            wall_bev = wall[view._pixel_row, view._pixel_col] & view.observable
            for side in ("left", "right"):
                label = tracker.last.get(side + "_label")
                if label is not None:
                    selected[side] = comp_stats(labels, label, view, wall_bev)
        result = dict(part=part, start=start, end=end, tier=tracker.tier,
                      error=None if observation is None else observation.error,
                      confidence=None if observation is None else observation.confidence,
                      selected=selected, pose=pose)
    cap.release()
    assert result is not None
    return result


if __name__ == "__main__":
    cases = [run(4, 492, 492), run(4, 470, 492),
             run(4, 470, 492, visual_odom=True), run(6, 96, 104)]
    assert [case["tier"] for case in cases] == ["STOP", "BOTH", "BOTH", "BOTH"]
    assert cases[1]["selected"]["left"]["wall_frac"] > .9
    assert cases[1]["selected"]["right"]["wall_frac"] > .7
    assert all(side["wall_frac"] < .05 for side in cases[3]["selected"].values())
    for case in cases:
        print(json.dumps(case))
