"""sim-model-lap 2026-10-09: same recorded frames through LaneKeeper with threshold paint vs the run's
model mask (fresh every frame, clean_learned_mask as the node does; no warp, no route context).
Separates "model paint" from "keeper logic": if threshold also fails on these frames it is not the model.
  ROSY_LEARNED_SITE=... python3 m26_pair.py <run dir> <t_from> <t_to> [--extra-model DIR ...]
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

import numpy as np

p = argparse.ArgumentParser()
p.add_argument("run", type=Path)
p.add_argument("t_from", type=float)
p.add_argument("t_to", type=float)
p.add_argument("--extra-model", action="append", default=[])
a = p.parse_args()
ws = a.run.parents[1]
sys.path.insert(0, str(ws / "src/rosy-platform/middleware/perception"))
from control.sensing.perception.camera_ground import GroundPlane  # noqa: E402
from control.sensing.perception.lane_containment import PAINT_HALF_WIDTH_M  # noqa: E402
from control.sensing.perception.lane_keep import LaneKeeper, clean_learned_mask  # noqa: E402
from control.sensing.perception.learned.runner import LaneSegModel, add_learned_site  # noqa: E402

add_learned_site()
cfg = json.loads((a.run / "config.json").read_text())
dirs = ([cfg["model"]] if cfg["model"] != "threshold" else []) + a.extra_model
models = {LaneSegModel.open(d).model_revision: LaneSegModel.open(d) for d in dirs}
first = json.loads((a.run / "rec/keep.jsonl").read_text().splitlines()[0])
proj = first["ground_projection"]
ground = GroundPlane(*(proj[k] for k in ("height_m", "pitch_rad", "focal_px", "principal_x", "principal_y", "max_range_m")))
keepers = {name: LaneKeeper(camera_x_offset_m=proj["camera_x_offset_m"], corner_turning=True,
                            paint_half_width_m=PAINT_HALF_WIDTH_M) for name in ("threshold", *models)}
rows = []
with np.load(a.run / "rec/frames.npz") as data:
    for i, s in enumerate(data["stamp"]):
        if not a.t_from <= s <= a.t_to:
            continue
        frame = data["frames"][i]
        row = {"stamp": round(float(s), 3), "gt": [round(float(v), 4) for v in data["gt"][i]]}
        for name, keeper in keepers.items():
            mask = None if name == "threshold" else clean_learned_mask(models[name].infer_mask(frame)[0], ground.horizon_row)
            keeper.update(frame, ground, paint_mask=mask, lane_half_width_m=0.0925)
            row[name] = f"{keeper.last['strategy']}/{keeper.last.get('reason')}" + ("/xwalk" if keeper.last.get("crosswalk") else "")
        rows.append(row)
for r in rows:
    print(r["stamp"], r["gt"][:2], {k: v for k, v in r.items() if k not in ("stamp", "gt")})
print("counts", {k: dict(Counter(r[k] for r in rows)) for k in keepers})
