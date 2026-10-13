"""Replay identical SIM frames through each learned paint model and LaneKeeper."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

import numpy as np


def replay(workspace: Path):
    sys.path.insert(0, str(workspace / "src/rosy-platform/middleware/perception"))
    from control.sensing.perception.camera_ground import GroundPlane
    from control.sensing.perception.lane_keep import LaneKeeper
    from control.sensing.perception.learned.runner import LaneSegModel

    names = ("pidnet", "unet", "v11", "v13_drivable")
    models = {name: LaneSegModel.open(workspace / "model_candidates" / name) for name in names}
    result = {"models": {name: model.model_revision for name, model in models.items()}, "sources": {}}
    for source in ("unet", "v13_drivable"):
        run = workspace / f"loop_{source}" / "lap_d567_baseline" / "rec"
        with np.load(run / "frames.npz") as data:
            first = json.loads((run / "keep.jsonl").read_text(encoding="utf-8").splitlines()[0])
            projection = first["ground_projection"]
            ground = GroundPlane(*(projection[key] for key in (
                "height_m", "pitch_rad", "focal_px", "principal_x", "principal_y", "max_range_m")))
            keepers = {name: LaneKeeper(camera_x_offset_m=projection["camera_x_offset_m"],
                                        corner_turning=True, paint_half_width_m=0.0125)
                       for name in ("threshold", *names)}
            rows = []
            for i, stamp in enumerate(data["stamp"]):
                if not 39.0 <= stamp <= 46.0:
                    continue
                frame = data["frames"][i]
                row = {"stamp": round(float(stamp), 3),
                       "gt_xy": [round(float(v), 4) for v in data["gt"][i, :2]], "models": {}}
                for name, keeper in keepers.items():
                    mask = None if name == "threshold" else models[name].infer_mask(frame)[0]
                    keeper.update(frame, ground, lane_half_width_m=0.0925, paint_mask=mask)
                    row["models"][name] = {
                        "strategy": keeper.last["strategy"], "reason": keeper.last.get("reason"),
                        "mask_pixels": None if mask is None else int(mask.sum())}
                rows.append(row)
        if len(rows) < 16 or any(a["stamp"] >= b["stamp"] for a, b in zip(rows, rows[1:])):
            raise ValueError("insufficient or unordered camera frames")
        result["sources"][source] = {
            "rows": rows,
            "strategy_counts_after_8_warmup_frames": {
                name: dict(Counter(row["models"][name]["strategy"] for row in rows[8:]))
                for name in keepers},
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    if not os.environ.get("ROSY_LEARNED_SITE"):
        raise SystemExit("ROSY_LEARNED_SITE must identify the ONNX Runtime site")
    print(json.dumps(replay(args.workspace), indent=2))
