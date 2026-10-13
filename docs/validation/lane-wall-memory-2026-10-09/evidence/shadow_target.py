"""Count candidate target/wall overlap without changing lane observations."""

import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "tools/perception_prototype/realrun"),
                str(ROOT / "middleware/perception"), str(ROOT / "contracts/foundation")]
from replay import GROUND, VIDEO, X_OFF, wall_mask  # noqa: E402
from control.sensing.perception.lane_keep import LaneKeeper  # noqa: E402


totals = dict(frames=0, output=0, target_inside=0, wall_target=0)
for part in range(1, 8):
    cap = cv2.VideoCapture(VIDEO % part)
    assert cap.isOpened(), VIDEO % part
    keeper = LaneKeeper(camera_x_offset_m=X_OFF, corner_turning=True)
    count = dict.fromkeys(totals, 0)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        count["frames"] += 1
        if keeper.update(frame, GROUND, lane_half_width_m=.0925) is None:
            continue
        count["output"] += 1
        target = keeper.last.get("target_px")
        if target is None:
            continue
        x, y = (int(round(value)) for value in target)
        if not (0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]):
            continue
        count["target_inside"] += 1
        wall, _ = wall_mask(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        count["wall_target"] += bool(wall[y, x])
    cap.release()
    print(json.dumps(dict(part=part, **count)))
    for key in totals:
        totals[key] += count[key]
assert totals == dict(frames=4981, output=3515, target_inside=2761, wall_target=95)
print(json.dumps(dict(total=totals)))
