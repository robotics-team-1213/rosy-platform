"""Evaluate a live-to-training translation on recorded fixed-camera frames.

Pass a JSON file with `camera` (top or side), `training_profile`, `live_profile`,
and paired `reference_xy` and `live_xy` arrays in native pixels. The first two
pairs are fitting anchors. The rest must be independent fixed points distributed
across the task image, including surfaces at other working heights. Run on
several independently captured pairs before considering a policy experiment.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

def translation_report(reference_xy, live_xy, *, max_shift_px, max_residual_px):
    if not all(math.isfinite(v) and v > 0 for v in (max_shift_px, max_residual_px)):
        raise ValueError("shift and residual limits must be positive and finite")
    ref, live = np.asarray(reference_xy, dtype=float), np.asarray(live_xy, dtype=float)
    if ref.ndim != 2 or ref.shape[1] != 2 or len(ref) < 4 or live.shape != ref.shape:
        raise ValueError("need two fit pairs and at least two held-out XY pairs")
    if any(not np.isfinite(points).all() or len(np.unique(points, axis=0)) != len(points) for points in (ref, live)):
        raise ValueError("anchor points must be distinct and finite")
    offsets = live - ref
    dx, dy = offsets[:2].mean(axis=0).tolist()
    before = np.linalg.norm(offsets, axis=1)
    after = np.linalg.norm(offsets - [dx, dy], axis=1)
    shift_px = math.hypot(dx, dy)
    fit_max, holdout_before, holdout_after = map(float, (after[:2].max(), before[2:].max(), after[2:].max()))
    eligible = (shift_px <= max_shift_px and max(fit_max, holdout_after) <= max_residual_px
                and np.all(after[2:] <= before[2:]) and holdout_after < holdout_before)
    return dict(live_offset_px=[dx, dy], shift_px=shift_px, fit_max_after_px=fit_max,
                holdout_max_before_px=holdout_before, holdout_max_after_px=holdout_after,
                holdout_before_px=before[2:].tolist(), holdout_after_px=after[2:].tolist(),
                max_shift_px=max_shift_px, max_residual_px=max_residual_px,
                candidate_matrix=[[1, 0, -dx], [0, 1, -dy]] if eligible else None)


def main(argv=None):
    import cv2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="recorded frame used for the model's training view")
    parser.add_argument("live", type=Path, help="recorded frame from the current camera")
    parser.add_argument("anchors", type=Path, help="JSON with matched stationary points")
    parser.add_argument("--max-shift-px", type=float, required=True)
    parser.add_argument("--max-residual-px", type=float, required=True)
    args = parser.parse_args(argv)
    records = {name: getattr(args, name).read_bytes() for name in ("reference", "live", "anchors")}
    hashes = {name: "sha256:" + hashlib.sha256(data).hexdigest() for name, data in records.items()}
    anchors = json.loads(records["anchors"])
    camera, profile = anchors.get("camera"), anchors.get("training_profile")
    if camera not in ("top", "side") or not isinstance(profile, str) or not profile or anchors.get("live_profile") != profile:
        parser.error("requires a fixed top or side camera and matching capture profiles")
    if any(anchors.get(f"{name}_sha256") != hashes[name] for name in ("reference", "live")):
        parser.error("anchor annotations must identify both original frame hashes")
    ref, live = (cv2.imdecode(np.frombuffer(records[name], np.uint8), cv2.IMREAD_COLOR) for name in ("reference", "live"))
    if ref is None or live is None or ref.shape != live.shape:
        parser.error("frames must be readable and at the same native resolution")
    height, width = ref.shape[:2]
    try:
        report = translation_report(anchors["reference_xy"], anchors["live_xy"],
                                    max_shift_px=args.max_shift_px, max_residual_px=args.max_residual_px)
        for key in ("reference_xy", "live_xy"):
            if not all(0 <= x < width and 0 <= y < height for x, y in anchors[key]):
                raise ValueError(f"{key} contains a point outside the frame")
    except (KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(dict(report, camera=camera, profile=profile, size=[width, height], **hashes), indent=2))
    return 0 if report["candidate_matrix"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
