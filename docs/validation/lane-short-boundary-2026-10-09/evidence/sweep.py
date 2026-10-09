"""Read-only post-fit line-length sweep on fixed SIM and existing real frames.

This monkeypatches line extraction only in this process; it does not edit the
product threshold or replay the closed-loop robot. Real frames may be absent.
"""

import collections
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from control.sensing.perception import lane_keep as lk


REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "middleware/perception/test"))
from test_lane_keep_bend import CAMERA_X, HALF, FIXTURE, LABELS, _ground, _off_centre, _real_decisions  # noqa: E402


def sim():
    data = np.load(FIXTURE)
    frames, meta = data["frames"], json.loads(str(data["meta"]))
    assert len(frames) == len(meta) == 89
    keepers = {}
    rows = []
    for index, (frame, item) in enumerate(zip(frames, meta)):
        keeper = keepers.setdefault(item["clip"], lk.LaneKeeper(
            camera_x_offset_m=CAMERA_X, corner_turning=True))
        keeper.update(frame, _ground(), lane_half_width_m=HALF, bend_expected=True)
        target = keeper.last["target_m"]
        rows.append({"index": index, "clip": item["clip"], "strategy": keeper.last["strategy"],
                     "drive": target is not None,
                     "target_error_mm": round(1000 * _off_centre(item["gt"], target), 1)
                     if target is not None else None})
    return rows


def compare(before, after):
    if isinstance(before, dict):
        assert before.keys() == after.keys()
    else:
        assert len(before) == len(after)
    pairs = ([(name, before[name][3] is not None, after[name][3] is not None,
               before[name] != after[name]) for name in before]
             if isinstance(before, dict) else
             [(old["index"], old["drive"], new["drive"], old["strategy"] != new["strategy"])
              for old, new in zip(before, after)])
    return {"drive_to_hold": [name for name, old, new, _ in pairs if old and not new],
            "hold_to_drive": [name for name, old, new, _ in pairs if not old and new],
            "changed": sum(changed for _, _, _, changed in pairs)}


def run():
    original = lk.extract_lines
    results = {}
    label_paths = sorted(LABELS.glob("*/frames/*.jpg"))
    label_hash = hashlib.sha256()
    for path in label_paths:
        label_hash.update(path.relative_to(LABELS).as_posix().encode())
        label_hash.update(hashlib.sha256(path.read_bytes()).digest())
    try:
        for limit in (0.06, 0.07, 0.08, 0.10):
            def filtered(*args, **kwargs):
                lines, blobs = original(*args, **kwargs)
                return ([line for line in lines
                         if line["along"][1] - line["along"][0] >= limit], blobs)

            lk.extract_lines = filtered
            rows = sim()
            real = ({str(bend_expected).lower(): _real_decisions(bend_expected)
                     for bend_expected in (False, True)}
                    if len(list(LABELS.glob("*/frames"))) >= 2 else None)
            results[str(limit)] = {"sim_rows": rows, "real": real}
    finally:
        lk.extract_lines = original
    baseline = results["0.06"]
    assert collections.Counter(r["strategy"] for r in baseline["sim_rows"]
                               if r["clip"] == "south_centre_lost") == {"bend_ahead": 8, "none": 3}
    report = {"real_frames": len(label_paths), "real_frame_set_sha256": label_hash.hexdigest(),
              "baseline_target_error_mm": {str(r["index"]): r["target_error_mm"]
                                           for r in baseline["sim_rows"] if 15 <= r["index"] <= 20},
              "sweeps": {}}
    for limit, result in results.items():
        rows = result["sim_rows"]
        report["sweeps"][limit] = {
            "sim_south_centre_lost": dict(collections.Counter(
                r["strategy"] for r in rows if r["clip"] == "south_centre_lost")),
            "sim_bend_flipping": dict(collections.Counter(
                r["strategy"] for r in rows if r["clip"] == "bend_flipping")),
            "sim_delta": compare(baseline["sim_rows"], rows),
            "real_delta": {mode: compare(baseline["real"][mode], result["real"][mode])
                           for mode in ("false", "true")} if result["real"] is not None else None,
        }
    assert report["sweeps"]["0.07"]["sim_delta"]["drive_to_hold"] == list(range(15, 21))
    return report


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
