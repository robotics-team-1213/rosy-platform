"""Replay a recorded keep run through LaneKeeper offline (model PC).
  python3 replay.py RUN_DIR SRC_PERCEPTION [--t0 40 --t1 48] [--fresh-at T ...] [--save-masks OUT.npz]
Masks: re-inferred (fresh, unwarped) from the run's model, cleaned like the node.
"""
import argparse, json, math, sys
from pathlib import Path
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("run", type=Path)
p.add_argument("src", type=Path)
p.add_argument("--t0", type=float, default=0.0)
p.add_argument("--t1", type=float, default=1e9)
p.add_argument("--show0", type=float, default=44.0)
p.add_argument("--fresh-at", type=float, nargs="*", default=[])
p.add_argument("--save-masks", type=Path)
a = p.parse_args()
sys.path.insert(0, str(a.src))
from control.sensing.perception.learned.runner import LaneSegModel, add_learned_site  # noqa
from control.sensing.perception.lane_keep import LaneKeeper, clean_learned_mask  # noqa
from control.sensing.perception.camera_ground import GroundPlane  # noqa
add_learned_site()
cfg = json.loads((a.run / "config.json").read_text())
keep = [json.loads(x) for x in (a.run / "rec/keep.jsonl").read_text().splitlines() if x.strip()]
by = {round(k["stamp"], 3): k for k in keep if k.get("stamp") is not None}
gp = next(k["ground_projection"] for k in keep if k.get("ground_projection"))
ground = GroundPlane(gp["height_m"], gp["pitch_rad"], gp["focal_px"], gp["principal_x"], gp["principal_y"], gp["max_range_m"])
model = None if cfg["model"] == "threshold" else LaneSegModel.open(cfg["model"])
data = np.load(a.run / "rec/frames.npz")
stamps = data["stamp"]
idx = [i for i, s in enumerate(stamps) if a.t0 <= s <= a.t1]
frames = [np.ascontiguousarray(data["frames"][i]) for i in idx]
masks = []
for f in frames:
    masks.append(None if model is None else clean_learned_mask(model.infer_mask(f)[0].astype(np.uint8), ground.horizon_row))
if a.save_masks:
    np.savez_compressed(a.save_masks, stamp=stamps[idx], frames=np.stack(frames),
                        masks=np.stack(masks) if model is not None else np.zeros(0))


def run(start_t):
    k = LaneKeeper(camera_x_offset_m=gp["camera_x_offset_m"], corner_turning=True)
    out = {}
    for i, f, m in zip(idx, frames, masks):
        s = round(float(stamps[i]), 3)
        if s < start_t:
            continue
        k.update(f, ground, paint_mask=m, lane_half_width_m=0.0925)
        out[s] = (k.last["strategy"], k.last.get("reason"),
                  [(c.get("side"), c.get("heading_deg"), c.get("length_m"), c.get("ends_m"), c.get("reason"))
                   for c in k.last["candidates"]], k._corner_side, k._corner_frames)
    return out


cont = run(a.t0)
fresh = {t: run(t) for t in a.fresh_at}
for i in idx:
    s = round(float(stamps[i]), 3)
    if s < a.show0:
        continue
    live = by.get(s, {})
    line = f"{s:7.3f} live={live.get('strategy')}/{live.get('reason')} cont={cont[s][0]}/{cont[s][1]} latch={cont[s][3]},{cont[s][4]}"
    for t, r in fresh.items():
        if s in r:
            line += f" fresh@{t}={r[s][0]}"
    print(line)
    for c in cont[s][2]:
        print("      ", c)
