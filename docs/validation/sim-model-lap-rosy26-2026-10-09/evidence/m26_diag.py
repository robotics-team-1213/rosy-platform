"""sim-model-lap 2026-10-09: frames + model masks + keep_debug around a stall (model PC, offline).

For each recorded camera frame in [t0 - before, t0 + after] (sim stamp), writes one PNG:
left = frame with keep_debug candidates (green selected, red rejected/transverse, yellow other),
right = this model's mask on the same frame (re-inferred, the run's model), plus timeline.json.
  ROSY_LEARNED_SITE=... python3 m26_diag.py <run dir> <t0> <out dir> [--before 3 --after 1]
"""
import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("run", type=Path)
p.add_argument("t0", type=float)
p.add_argument("out", type=Path)
p.add_argument("--before", type=float, default=3.0)
p.add_argument("--after", type=float, default=1.0)
p.add_argument("--step", type=int, default=1)
a = p.parse_args()

ws = a.run.parents[1]
sys.path.insert(0, str(ws / "src/rosy-platform/middleware/perception"))
from control.sensing.perception.learned.runner import LaneSegModel, add_learned_site  # noqa: E402

add_learned_site()
cfg = json.loads((a.run / "config.json").read_text())
model = None if cfg["model"] == "threshold" else LaneSegModel.open(cfg["model"])
keep = [json.loads(x) for x in (a.run / "rec/keep.jsonl").read_text().splitlines() if x.strip()]
by_stamp = {round(k["stamp"], 3): k for k in keep if k.get("stamp") is not None}
a.out.mkdir(parents=True, exist_ok=True)
timeline = []
with np.load(a.run / "rec/frames.npz") as data:
    stamps = data["stamp"]
    idx = [i for i, s in enumerate(stamps) if a.t0 - a.before <= s <= a.t0 + a.after][::a.step]
    for i in idx:
        s = round(float(stamps[i]), 3)
        frame = np.ascontiguousarray(data["frames"][i])
        k = by_stamp.get(s) or min(keep, key=lambda r: abs((r.get("stamp") or -1e9) - s))
        left = frame.copy()
        for kind, colour in (("candidates", None), ("transverse", (0, 0, 255))):
            for c in k.get(kind) or []:
                col = colour or ((0, 255, 0) if c.get("selected") else (0, 0, 255) if c.get("rejected") else (0, 255, 255))
                (x0, y0), (x1, y1) = c["ends_px"]
                cv2.line(left, (int(x0), int(y0)), (int(x1), int(y1)), col, 2)
        if k.get("target_px"):
            cv2.circle(left, tuple(int(v) for v in k["target_px"]), 4, (255, 0, 255), -1)
        right = frame.copy()
        if model is not None:
            mask = model.infer_mask(frame)[0].astype(bool)
            right[mask] = (0.4 * right[mask] + 0.6 * np.array([255, 0, 255])).astype(np.uint8)
            mask_px = int(mask.sum())
        else:
            mask_px = None
        img = np.concatenate([left, right], axis=1)
        text = f"t={s} {k.get('strategy')} {k.get('reason')} src={k.get('paint_source_used')} reuse={k.get('paint_reuse')}"
        cv2.putText(img, text, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        name = f"{s:08.3f}.png"
        cv2.imwrite(str(a.out / name), img)
        timeline.append({"stamp": s, "png": name, "gt": [round(float(v), 4) for v in data["gt"][i]],
                         "strategy": k.get("strategy"), "reason": k.get("reason"),
                         "paint_source_used": k.get("paint_source_used"), "paint_reuse": k.get("paint_reuse"),
                         "paint_mask_age_s": k.get("paint_mask_age_s"), "mask_px_now": mask_px,
                         "candidates": [{kk: c.get(kk) for kk in ("side", "heading_deg", "length_m", "selected", "rejected", "reason")}
                                        for c in k.get("candidates") or []],
                         "transverse": len(k.get("transverse") or [])})
(a.out / "timeline.json").write_text(json.dumps(timeline, indent=1))
print(len(timeline), "frames ->", a.out)
